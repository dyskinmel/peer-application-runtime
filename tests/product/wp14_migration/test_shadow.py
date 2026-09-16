from __future__ import annotations
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from product.wp14.par_migration import MigrationError, TARGET_SCHEMA_ID, TARGET_STORE_VERSION, create_verified_backup
from product.wp14.par_migration.backup import migration_directory
from product.wp14.par_migration.journal import MigrationJournal
from product.wp14.par_migration.shadow import build_shadow, verify_shadow
from support import create_store_and_plan


def rows(connection, table, order):
    return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]


class ShadowTests(unittest.TestCase):
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

    def build(self):
        create_verified_backup(self.plan)
        return build_shadow(self.plan)

    def paths(self):
        root = migration_directory(self.plan)
        return root / "backup" / "store.sqlite", root / "shadow" / "store.sqlite"

    def test_backup_is_required_before_shadow(self):
        self.assert_code("BACKUP_REQUIRED", lambda: build_shadow(self.plan))

    def test_shadow_preserves_ledger_outbox_and_drafts_exactly(self):
        stages = []
        create_verified_backup(self.plan)
        manifest = build_shadow(self.plan, observer=stages.append)
        self.assertEqual(stages, ["shadow.after_schema", "shadow.after_rows", "shadow.after_fsync", "verify.after_shadow"])
        self.assertTrue(manifest.logical_verified)
        self.assertTrue(manifest.schema_verified)
        self.assertTrue(manifest.hash_verified)
        self.assertEqual(manifest.inventory, self.plan.inventory)
        backup, shadow = self.paths()
        with sqlite3.connect(backup) as source, sqlite3.connect(shadow) as target:
            for table, order in (("operation_ledger", "operation_id"), ("outbox", "operation_id"), ("drafts", "draft_id")):
                self.assertEqual(rows(source, table, order), rows(target, table, order))
            metadata = target.execute("SELECT generation,source_generation,schema_id,store_version,source_digest,plan_digest,converter_digest FROM store_metadata WHERE singleton=1").fetchone()
            self.assertEqual(metadata[0], self.plan.target_generation)
            self.assertEqual(metadata[1], self.plan.source_generation)
            self.assertEqual(metadata[2:4], (TARGET_SCHEMA_ID, TARGET_STORE_VERSION))
            self.assertEqual(metadata[4:], (self.plan.source_digest, self.plan.plan_digest, self.plan.converter_digest))
            self.assertEqual(target.execute("PRAGMA user_version").fetchone()[0], TARGET_STORE_VERSION)
        self.assertEqual(MigrationJournal.load(self.plan).stage, "SHADOW_VERIFIED")
        self.assertEqual(MigrationJournal.load(self.plan).sequence, 3)
        self.assertEqual(verify_shadow(self.plan), manifest)

    def test_unknown_mandatory_codec_is_opaque_upgrade_required(self):
        manifest = self.build()
        self.assertEqual(manifest.unknown_mandatory_count, 1)
        backup, shadow = self.paths()
        with sqlite3.connect(backup) as source, sqlite3.connect(shadow) as target:
            original = source.execute("SELECT signed_bytes FROM signed_objects WHERE object_id='unknown-1'").fetchone()[0]
            migrated = target.execute("SELECT codec,mandatory,signed_bytes,applied,ack_state,resigned,migration_status FROM signed_objects WHERE object_id='unknown-1'").fetchone()
            self.assertEqual(migrated, ("vendor.future.v9", 1, original, 0, "BLOCKED", 0, "UPGRADE_REQUIRED"))
            known = target.execute("SELECT signed_bytes,applied,ack_state,resigned,migration_status FROM signed_objects WHERE object_id='known-1'").fetchone()
            self.assertEqual(known, (b"signed-known", 1, "ACKED", 0, "PRESERVED"))

    def test_ack_unknown_operation_is_not_replayed_or_rewritten(self):
        self.build()
        _, shadow = self.paths()
        with sqlite3.connect(shadow) as target:
            self.assertEqual(target.execute("SELECT state,outcome FROM operation_ledger WHERE operation_id='op-001'").fetchone(), ("OUTCOME_UNKNOWN", "UNKNOWN"))
            self.assertEqual(target.execute("SELECT state,envelope FROM outbox WHERE operation_id='op-001'").fetchone(), ("IN_FLIGHT", b"pending-envelope"))
            self.assertEqual(target.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0], 2)

    def test_seed_frontier_and_converter_are_pinned(self):
        manifest = self.build()
        _, shadow = self.paths()
        with sqlite3.connect(shadow) as target:
            seed, frontier, converter, source_digest = target.execute("SELECT seed_bytes,source_frontier,converter_digest,source_digest FROM migration_seed WHERE singleton=1").fetchone()
        self.assertEqual(hashlib.sha256(seed).hexdigest(), self.plan.seed_sha256)
        self.assertEqual(hashlib.sha256(frontier).hexdigest(), self.plan.frontier_sha256)
        self.assertEqual(converter, self.plan.converter_digest)
        self.assertEqual(source_digest, self.plan.source_digest)
        self.assertEqual(manifest.seed_sha256, self.plan.seed_sha256)
        self.assertEqual(manifest.frontier_sha256, self.plan.frontier_sha256)

    def test_missing_outbox_or_changed_signed_bytes_is_rejected(self):
        self.build()
        _, shadow = self.paths()
        with sqlite3.connect(shadow) as target:
            target.execute("DELETE FROM outbox WHERE operation_id='op-001'")
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(self.plan))

        other_store, other_work, other_plan = create_store_and_plan(self.base / "other")
        create_verified_backup(other_plan)
        build_shadow(other_plan)
        other_shadow = migration_directory(other_plan) / "shadow" / "store.sqlite"
        with sqlite3.connect(other_shadow) as target:
            target.execute("UPDATE signed_objects SET signed_bytes=? WHERE object_id='unknown-1'", (b"rewritten",))
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(other_plan))

    def test_schema_or_unknown_codec_resign_mutant_is_rejected(self):
        self.build()
        _, shadow = self.paths()
        with sqlite3.connect(shadow) as target:
            target.execute("UPDATE signed_objects SET applied=1,ack_state='ACKED',resigned=1,migration_status='PRESERVED' WHERE object_id='unknown-1'")
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(self.plan))

        other_store, other_work, other_plan = create_store_and_plan(self.base / "other")
        create_verified_backup(other_plan)
        build_shadow(other_plan)
        other_shadow = migration_directory(other_plan) / "shadow" / "store.sqlite"
        with sqlite3.connect(other_shadow) as target:
            target.execute("CREATE TABLE unexpected_table(value TEXT)")
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(other_plan))

    def test_incomplete_shadow_pending_is_rebuilt(self):
        create_verified_backup(self.plan)
        pending = migration_directory(self.plan) / "shadow.pending"
        pending.mkdir()
        (pending / "partial").write_bytes(b"partial")
        manifest = build_shadow(self.plan)
        self.assertTrue(manifest.logical_verified)
        self.assertFalse(pending.exists())

    def test_manifest_tamper_or_extra_file_is_rejected(self):
        self.build()
        shadow_root = migration_directory(self.plan) / "shadow"
        manifest_path = shadow_root / "MANIFEST.json"
        raw = json.loads(manifest_path.read_text())
        raw["logicalVerified"] = False
        manifest_path.write_text(json.dumps(raw))
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(self.plan))

        other_store, other_work, other_plan = create_store_and_plan(self.base / "other")
        create_verified_backup(other_plan)
        build_shadow(other_plan)
        (migration_directory(other_plan) / "shadow" / "extra").write_bytes(b"extra")
        self.assert_code("SHADOW_INVALID", lambda: verify_shadow(other_plan))


if __name__ == "__main__":
    unittest.main()
