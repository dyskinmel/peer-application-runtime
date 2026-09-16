from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from product.wp14.par_migration import MigrationError
from product.wp14.par_migration.backup import (
    create_verified_backup,
    migration_directory,
    require_verified_backup,
    verify_backup,
)
from product.wp14.par_migration.journal import MigrationJournal
from support import content_digest, create_store_and_plan, refresh_pointer_hash


class BackupTests(unittest.TestCase):
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

    def test_backup_is_copied_fsynced_manifested_and_read_back(self):
        source_before = content_digest(self.store)
        stages = []
        manifest = create_verified_backup(self.plan, observer=stages.append)
        self.assertEqual(stages, ["backup.before_copy", "backup.after_copy", "backup.after_readback"])
        self.assertEqual(content_digest(self.store), source_before)
        self.assertEqual(manifest.plan_digest, self.plan.plan_digest)
        self.assertEqual(manifest.source_digest, self.plan.source_digest)
        self.assertTrue(manifest.readback_verified)
        self.assertEqual(manifest.inventory, self.plan.inventory)
        backup = migration_directory(self.plan) / "backup"
        self.assertEqual({p.name for p in backup.iterdir()}, {"MANIFEST.json", "store.sqlite"})
        self.assertEqual(verify_backup(self.plan), manifest)
        self.assertEqual(require_verified_backup(self.plan), manifest)
        journal = MigrationJournal.load(self.plan)
        self.assertEqual(journal.stage, "BACKUP_VERIFIED")
        self.assertEqual(journal.sequence, 1)
        saved_plan = json.loads((migration_directory(self.plan) / "PLAN.json").read_text())
        self.assertEqual(saved_plan, self.plan.to_dict())

    def test_missing_backup_is_a_hard_prerequisite(self):
        self.assert_code("BACKUP_REQUIRED", lambda: require_verified_backup(self.plan))

    def test_tampered_backup_file_is_rejected(self):
        create_verified_backup(self.plan)
        db = migration_directory(self.plan) / "backup" / "store.sqlite"
        with db.open("ab") as stream:
            stream.write(b"tamper")
        self.assert_code("BACKUP_INVALID", lambda: verify_backup(self.plan))

    def test_tampered_manifest_or_extra_file_is_rejected(self):
        create_verified_backup(self.plan)
        backup = migration_directory(self.plan) / "backup"
        manifest_path = backup / "MANIFEST.json"
        raw = json.loads(manifest_path.read_text())
        raw["planDigest"] = "0" * 64
        manifest_path.write_text(json.dumps(raw))
        self.assert_code("BACKUP_INVALID", lambda: verify_backup(self.plan))
        # Rebuild in a fresh fixture, then prove unlisted content is rejected.
        other_store, other_work, other_plan = create_store_and_plan(self.base / "other")
        create_verified_backup(other_plan)
        other_backup = migration_directory(other_plan) / "backup"
        (other_backup / "unlisted-secret").write_bytes(b"not in manifest")
        self.assert_code("BACKUP_INVALID", lambda: verify_backup(other_plan))

    def test_incomplete_owned_backup_is_replaced_on_resume(self):
        pending = migration_directory(self.plan, create=True) / "backup.pending"
        pending.mkdir()
        (pending / "partial").write_bytes(b"partial")
        manifest = create_verified_backup(self.plan)
        self.assertTrue(manifest.readback_verified)
        self.assertFalse(pending.exists())
        self.assertEqual(MigrationJournal.load(self.plan).stage, "BACKUP_VERIFIED")

    def test_source_digest_change_refuses_journal_reuse(self):
        pointer = json.loads((self.store / "ACTIVE.json").read_text())
        db = self.store / "generations" / pointer["generation"] / "store.sqlite"
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE drafts SET payload=? WHERE draft_id='draft-1'", (b"changed-after-plan",))
        refresh_pointer_hash(self.store)
        self.assert_code("SOURCE_DIGEST_MISMATCH", lambda: create_verified_backup(self.plan))
        self.assertFalse((self.work / self.plan.migration_id / "backup").exists())

    def test_symlink_in_backup_is_rejected(self):
        create_verified_backup(self.plan)
        backup = migration_directory(self.plan) / "backup"
        target = self.base / "outside"
        target.write_bytes(b"outside")
        (backup / "link").symlink_to(target)
        self.assert_code("BACKUP_INVALID", lambda: verify_backup(self.plan))

    def test_plan_identity_tamper_is_rejected(self):
        create_verified_backup(self.plan)
        plan_path = migration_directory(self.plan) / "PLAN.json"
        raw = json.loads(plan_path.read_text())
        raw["sourceDigest"] = "f" * 64
        plan_path.write_text(json.dumps(raw))
        self.assert_code("PLAN_IDENTITY_MISMATCH", lambda: create_verified_backup(self.plan))


if __name__ == "__main__":
    unittest.main()
