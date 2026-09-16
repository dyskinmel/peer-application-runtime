from __future__ import annotations
import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path

from product.wp14.par_migration import (
    DEFAULT_VERSIONS,
    SOURCE_SCHEMA_ID,
    MigrationError,
    create_v1_store,
    inspect_generation,
    plan_migration,
    read_active_pointer,
)


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    if not root.exists():
        return h.hexdigest()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix().encode()
        h.update(rel + b"\0")
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def sample_rows():
    return {
        "ledger": [
            {"operation_id": "op-001", "state": "OUTCOME_UNKNOWN", "payload_hash": "11" * 32, "outcome": "UNKNOWN"},
            {"operation_id": "op-002", "state": "COMMITTED", "payload_hash": "22" * 32, "outcome": "APPLIED"},
        ],
        "outbox": [
            {"operation_id": "op-001", "envelope": b"pending-envelope", "state": "IN_FLIGHT"},
        ],
        "drafts": [
            {"draft_id": "draft-1", "document_id": "doc-1", "payload": b"private-draft", "applied": 0},
        ],
        "signed_objects": [
            {"object_id": "known-1", "codec": "par.change.v1", "mandatory": 1, "signed_bytes": b"signed-known", "applied": 1, "ack_state": "ACKED", "resigned": 0},
            {"object_id": "unknown-1", "codec": "vendor.future.v9", "mandatory": 1, "signed_bytes": b"signed-unknown", "applied": 0, "ack_state": "PENDING", "resigned": 0},
        ],
    }


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name)
        self.store = self.base / "store-root"
        self.work = self.base / "migration-work"
        rows = sample_rows()
        create_v1_store(
            self.store,
            generation="gen-source-0001",
            versions=DEFAULT_VERSIONS,
            ledger=rows["ledger"],
            outbox=rows["outbox"],
            drafts=rows["drafts"],
            signed_objects=rows["signed_objects"],
            seed_bytes=b"approved-seed-bytes",
            source_frontier=b"frontier-root-001",
        )

    def tearDown(self):
        self.td.cleanup()

    def plan(self, **kwargs):
        return plan_migration(
            self.store,
            self.work,
            observed_at="2026-09-11T19:30:00-05:00",
            capacity_reader=lambda _: 10**9,
            **kwargs,
        )

    def refresh_pointer_hash(self):
        pointer_path = self.store / "ACTIVE.json"
        pointer = json.loads(pointer_path.read_text())
        db = self.store / "generations" / pointer["generation"] / "store.sqlite"
        pointer["storeSha256"] = hashlib.sha256(db.read_bytes()).hexdigest()
        pointer_path.write_text(json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n")

    def assert_code(self, code, callable_):
        with self.assertRaises(MigrationError) as cm:
            callable_()
        self.assertEqual(cm.exception.code, code)

    def test_plan_is_read_only_and_does_not_create_work_root(self):
        before = tree_digest(self.store)
        self.assertFalse(self.work.exists())
        plan = self.plan()
        self.assertEqual(tree_digest(self.store), before)
        self.assertFalse(self.work.exists())
        self.assertEqual(plan.source_generation, "gen-source-0001")
        self.assertEqual(plan.versions, DEFAULT_VERSIONS)
        self.assertEqual(plan.versions["schema"], SOURCE_SCHEMA_ID)
        self.assertEqual(plan.inventory, {"drafts": 1, "operationLedger": 2, "outbox": 1, "signedObjects": 2})
        self.assertGreater(plan.required_bytes, plan.source_size)
        self.assertEqual(plan.available_bytes, 10**9)
        self.assertRegex(plan.plan_digest, r"^[0-9a-f]{64}$")
        self.assertTrue(plan.migration_id.startswith("migration-"))
        self.assertTrue(plan.target_generation.startswith("generation-"))

    def test_plan_has_independent_versions_and_canonical_identity(self):
        first = self.plan()
        second = self.plan()
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(set(first.versions), {"wire", "suite", "schema", "store", "sdk", "ui"})
        changed = dict(DEFAULT_VERSIONS)
        changed["sdk"] = "0057-alt"
        other = self.base / "other-store"
        rows = sample_rows()
        create_v1_store(other, generation="gen-source-0001", versions=changed, ledger=rows["ledger"], outbox=rows["outbox"], drafts=rows["drafts"], signed_objects=rows["signed_objects"], seed_bytes=b"approved-seed-bytes", source_frontier=b"frontier-root-001")
        other_plan = plan_migration(other, self.base / "other-work", observed_at="2026-09-11T19:30:00-05:00", capacity_reader=lambda _: 10**9)
        self.assertNotEqual(first.plan_digest, other_plan.plan_digest)
        self.assertNotEqual(first.source_digest, other_plan.source_digest)

    def test_planner_does_not_use_network(self):
        original = socket.socket
        def forbidden(*args, **kwargs):
            raise AssertionError("network attempted")
        socket.socket = forbidden
        try:
            self.assertEqual(self.plan().source_generation, "gen-source-0001")
        finally:
            socket.socket = original

    def test_active_pointer_and_observation_are_strict(self):
        pointer = read_active_pointer(self.store)
        observation = inspect_generation(self.store, pointer.generation)
        self.assertEqual(pointer.store_sha256, observation.store_sha256)
        self.assertEqual(observation.versions, DEFAULT_VERSIONS)
        self.assertEqual(observation.seed_sha256, hashlib.sha256(b"approved-seed-bytes").hexdigest())
        self.assertEqual(observation.frontier_sha256, hashlib.sha256(b"frontier-root-001").hexdigest())
        raw = json.loads((self.store / "ACTIVE.json").read_text())
        raw["unknown"] = True
        (self.store / "ACTIVE.json").write_text(json.dumps(raw))
        self.assert_code("ACTIVE_POINTER_INVALID", lambda: read_active_pointer(self.store))

    def test_unknown_or_downgrade_store_version_is_upgrade_required(self):
        pointer = read_active_pointer(self.store)
        db = self.store / "generations" / pointer.generation / "store.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE store_metadata SET store_version=99, schema_id='future-v99' WHERE singleton=1")
            conn.execute("PRAGMA user_version=99")
        self.refresh_pointer_hash()
        raw = json.loads((self.store / "ACTIVE.json").read_text())
        raw["storeVersion"] = 99
        (self.store / "ACTIVE.json").write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
        self.assert_code("UPGRADE_REQUIRED", self.plan)

    def test_wal_or_shm_sidecar_is_refused(self):
        pointer = read_active_pointer(self.store)
        db = self.store / "generations" / pointer.generation / "store.sqlite"
        (Path(str(db) + "-wal")).write_bytes(b"not-a-stable-source")
        self.assert_code("SOURCE_NOT_QUIESCENT", self.plan)

    def test_corrupt_or_unexpected_schema_is_refused(self):
        pointer = read_active_pointer(self.store)
        db = self.store / "generations" / pointer.generation / "store.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("DROP TABLE drafts")
        self.refresh_pointer_hash()
        self.assert_code("SOURCE_SCHEMA_INVALID", self.plan)

    def test_insufficient_capacity_is_refused_without_writes(self):
        before = tree_digest(self.store)
        self.assert_code(
            "INSUFFICIENT_SPACE",
            lambda: plan_migration(self.store, self.work, observed_at="2026-09-11T19:30:00-05:00", capacity_reader=lambda _: 1),
        )
        self.assertEqual(tree_digest(self.store), before)
        self.assertFalse(self.work.exists())

    def test_source_digest_changes_when_valid_source_content_changes(self):
        first = self.plan()
        other = self.base / "changed-store"
        rows = sample_rows()
        rows["drafts"][0]["payload"] = b"changed-private-draft"
        create_v1_store(other, generation="gen-source-0001", versions=DEFAULT_VERSIONS, ledger=rows["ledger"], outbox=rows["outbox"], drafts=rows["drafts"], signed_objects=rows["signed_objects"], seed_bytes=b"approved-seed-bytes", source_frontier=b"frontier-root-001")
        changed = plan_migration(other, self.base / "changed-work", observed_at="2026-09-11T19:30:00-05:00", capacity_reader=lambda _: 10**9)
        self.assertNotEqual(first.source_digest, changed.source_digest)
        self.assertNotEqual(first.plan_digest, changed.plan_digest)


if __name__ == "__main__":
    unittest.main()
