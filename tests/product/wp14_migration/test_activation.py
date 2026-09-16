from __future__ import annotations

from contextlib import closing

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from product.wp14.par_migration import (
    MigrationError,
    MigrationJournal,
    build_shadow,
    create_verified_backup,
    read_active_pointer,
)
from product.wp14.par_migration.backup import migration_directory
from product.wp14.par_migration.engine import (
    open_active_readonly,
    resume_migration,
    run_migration,
)
from support import create_store_and_plan, refresh_pointer_hash


class StopAtStage(RuntimeError):
    pass


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name)
        self.store, self.work, self.plan = create_store_and_plan(self.base)

    def tearDown(self):
        self.td.cleanup()

    def assert_code(self, code, callable_):
        with self.assertRaises(MigrationError) as cm:
            callable_()
        self.assertEqual(cm.exception.code, code)

    def stop_at(self, wanted):
        def observer(stage):
            if stage == wanted:
                raise StopAtStage(stage)
        return observer

    def target_root(self):
        return self.store / "generations" / self.plan.target_generation

    def test_normal_activation_is_atomic_and_retains_old_generation(self):
        result = run_migration(self.plan)
        pointer = read_active_pointer(self.store)
        self.assertTrue(result.activated)
        self.assertEqual(result.active_generation, self.plan.target_generation)
        self.assertEqual(pointer.generation, self.plan.target_generation)
        self.assertEqual(pointer.store_version, 2)
        self.assertEqual(pointer.store_sha256, result.target_store_sha256)
        self.assertTrue((self.store / "generations" / self.plan.source_generation / "store.sqlite").is_file())
        self.assertTrue((self.target_root() / "store.sqlite").is_file())
        self.assertTrue((self.target_root() / "MANIFEST.json").is_file())
        self.assertFalse((migration_directory(self.plan) / "shadow").exists())
        journal = MigrationJournal.load(self.plan)
        self.assertEqual((journal.stage, journal.sequence), ("ACTIVATED", 5))
        with closing(open_active_readonly(self.store)) as connection:
            metadata = connection.execute(
                "SELECT generation,source_generation,store_version FROM store_metadata WHERE singleton=1"
            ).fetchone()
        self.assertEqual(tuple(metadata), (self.plan.target_generation, self.plan.source_generation, 2))

    def test_unverified_shadow_is_never_published(self):
        create_verified_backup(self.plan)
        build_shadow(self.plan)
        shadow = migration_directory(self.plan) / "shadow" / "store.sqlite"
        with sqlite3.connect(shadow) as connection:
            connection.execute("DELETE FROM outbox WHERE operation_id='op-001'")
        self.assert_code("SHADOW_INVALID", lambda: run_migration(self.plan))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        self.assertFalse(self.target_root().exists())

    def test_source_digest_change_blocks_publish_and_switch(self):
        create_verified_backup(self.plan)
        build_shadow(self.plan)
        source = self.store / "generations" / self.plan.source_generation / "store.sqlite"
        with sqlite3.connect(source) as connection:
            connection.execute("UPDATE drafts SET payload=? WHERE draft_id='draft-1'", (b"changed",))
        refresh_pointer_hash(self.store)
        self.assert_code("SOURCE_DIGEST_MISMATCH", lambda: run_migration(self.plan))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        self.assertFalse(self.target_root().exists())

    def test_invalid_active_pointer_is_rejected_without_repair(self):
        pointer_path = self.store / "ACTIVE.json"
        raw = json.loads(pointer_path.read_text())
        raw["unexpected"] = True
        pointer_path.write_text(json.dumps(raw))
        before = pointer_path.read_bytes()
        self.assert_code("ACTIVE_POINTER_INVALID", lambda: run_migration(self.plan))
        self.assertEqual(pointer_path.read_bytes(), before)

    def test_live_migration_lease_blocks_a_second_writer(self):
        import fcntl
        import os

        lock_path = self.store / ".migration.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_code("MIGRATION_BUSY", lambda: run_migration(self.plan))
            self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_cross_device_publish_is_refused(self):
        create_verified_backup(self.plan)
        build_shadow(self.plan)
        with patch("product.wp14.par_migration.engine._device_id", side_effect=[11, 22]):
            self.assert_code("CROSS_DEVICE_PUBLISH", lambda: run_migration(self.plan))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        self.assertTrue((migration_directory(self.plan) / "shadow").is_dir())
        self.assertFalse(self.target_root().exists())

    def test_resume_after_publish_before_pointer_converges(self):
        with self.assertRaises(StopAtStage):
            run_migration(self.plan, observer=self.stop_at("publish.after_rename"))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        self.assertTrue(self.target_root().is_dir())
        self.assertFalse((migration_directory(self.plan) / "shadow").exists())
        self.assertEqual(MigrationJournal.load(self.plan).stage, "SHADOW_VERIFIED")
        result = resume_migration(self.plan)
        self.assertTrue(result.activated)
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.target_generation)
        self.assertEqual(MigrationJournal.load(self.plan).stage, "ACTIVATED")

    def test_resume_after_pointer_replace_converges(self):
        with self.assertRaises(StopAtStage):
            run_migration(self.plan, observer=self.stop_at("switch.after_replace"))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.target_generation)
        self.assertEqual(MigrationJournal.load(self.plan).stage, "PUBLISHED")
        result = resume_migration(self.plan)
        self.assertTrue(result.activated)
        self.assertEqual(MigrationJournal.load(self.plan).stage, "ACTIVATED")

    def test_resume_before_pointer_replace_discards_owned_temp_and_converges(self):
        with self.assertRaises(StopAtStage):
            run_migration(self.plan, observer=self.stop_at("switch.before_replace"))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.source_generation)
        temps = list(self.store.glob(".ACTIVE.*.pending"))
        self.assertEqual(len(temps), 1)
        result = resume_migration(self.plan)
        self.assertTrue(result.activated)
        self.assertFalse(list(self.store.glob(".ACTIVE.*.pending")))
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.target_generation)

    def test_repeated_resume_is_idempotent(self):
        first = run_migration(self.plan)
        first_pointer = (self.store / "ACTIVE.json").read_bytes()
        first_target = (self.target_root() / "store.sqlite").read_bytes()
        for _ in range(3):
            result = resume_migration(self.plan)
            self.assertEqual(result, first)
            self.assertEqual((self.store / "ACTIVE.json").read_bytes(), first_pointer)
            self.assertEqual((self.target_root() / "store.sqlite").read_bytes(), first_target)
        self.assertEqual(sorted(path.name for path in (self.store / "generations").iterdir()), sorted([self.plan.source_generation, self.plan.target_generation]))

    def test_open_refuses_downgrade_unknown_and_forced_version(self):
        run_migration(self.plan)
        self.assert_code("DOWNGRADE_REFUSED", lambda: open_active_readonly(self.store, supported_versions={1}))

        pointer_path = self.store / "ACTIVE.json"
        raw = json.loads(pointer_path.read_text())
        raw["storeVersion"] = 1
        pointer_path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
        self.assert_code("ACTIVE_POINTER_MISMATCH", lambda: open_active_readonly(self.store))

        raw["storeVersion"] = 99
        pointer_path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
        self.assert_code("UPGRADE_REQUIRED", lambda: open_active_readonly(self.store))

    def test_open_source_v1_readonly_before_migration(self):
        with closing(open_active_readonly(self.store)) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0], 2)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM operation_ledger")


if __name__ == "__main__":
    unittest.main()
