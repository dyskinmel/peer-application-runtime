from __future__ import annotations
import hashlib
import json
from pathlib import Path

from product.wp14.par_migration import DEFAULT_VERSIONS, create_v1_store, plan_migration


def sample_rows():
    return {
        "ledger": [
            {"operation_id": "op-001", "state": "OUTCOME_UNKNOWN", "payload_hash": "11" * 32, "outcome": "UNKNOWN"},
            {"operation_id": "op-002", "state": "COMMITTED", "payload_hash": "22" * 32, "outcome": "APPLIED"},
        ],
        "outbox": [{"operation_id": "op-001", "envelope": b"pending-envelope", "state": "IN_FLIGHT"}],
        "drafts": [{"draft_id": "draft-1", "document_id": "doc-1", "payload": b"private-draft", "applied": 0}],
        "signed_objects": [
            {"object_id": "known-1", "codec": "par.change.v1", "mandatory": 1, "signed_bytes": b"signed-known", "applied": 1, "ack_state": "ACKED", "resigned": 0},
            {"object_id": "unknown-1", "codec": "vendor.future.v9", "mandatory": 1, "signed_bytes": b"signed-unknown", "applied": 0, "ack_state": "PENDING", "resigned": 0},
        ],
    }


def create_store_and_plan(base: Path):
    store = base / "store-root"
    work = base / "migration-work"
    rows = sample_rows()
    create_v1_store(
        store,
        generation="gen-source-0001",
        versions=DEFAULT_VERSIONS,
        ledger=rows["ledger"],
        outbox=rows["outbox"],
        drafts=rows["drafts"],
        signed_objects=rows["signed_objects"],
        seed_bytes=b"approved-seed-bytes",
        source_frontier=b"frontier-root-001",
    )
    plan = plan_migration(store, work, observed_at="2026-09-11T19:30:00-05:00", capacity_reader=lambda _: 10**9)
    return store, work, plan


def content_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        h.update(path.relative_to(root).as_posix().encode() + b"\0")
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def refresh_pointer_hash(store: Path):
    pointer_path = store / "ACTIVE.json"
    pointer = json.loads(pointer_path.read_text())
    db = store / "generations" / pointer["generation"] / "store.sqlite"
    pointer["storeSha256"] = hashlib.sha256(db.read_bytes()).hexdigest()
    pointer_path.write_text(json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n")
