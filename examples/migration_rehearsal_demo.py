#!/usr/bin/env python3
"""Closed local migration rehearsal; no native build, device, G9 or egress claim."""
from __future__ import annotations

from contextlib import closing

import json
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from product.wp14.par_migration import (
    DEFAULT_VERSIONS,
    create_v1_store,
    open_active_readonly,
    plan_migration,
    run_migration,
)


def main() -> int:
    egress_attempts = 0
    original_socket = socket.socket

    def blocked_socket(*args, **kwargs):
        nonlocal egress_attempts
        egress_attempts += 1
        raise RuntimeError("NETWORK_FORBIDDEN")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = root / "store"
        work = root / "work"
        create_v1_store(
            store,
            generation="demo-source-0001",
            versions=DEFAULT_VERSIONS,
            ledger=[
                {
                    "operation_id": "op-demo",
                    "state": "OUTCOME_UNKNOWN",
                    "payload_hash": "11" * 32,
                    "outcome": "UNKNOWN",
                }
            ],
            outbox=[
                {
                    "operation_id": "op-demo",
                    "envelope": b"demo-pending-envelope",
                    "state": "IN_FLIGHT",
                }
            ],
            drafts=[
                {
                    "draft_id": "draft-demo",
                    "document_id": "doc-demo",
                    "payload": b"demo-private-draft",
                    "applied": 0,
                }
            ],
            signed_objects=[
                {
                    "object_id": "future-demo",
                    "codec": "vendor.future.v9",
                    "mandatory": 1,
                    "signed_bytes": b"opaque-signed-demo",
                    "applied": 0,
                    "ack_state": "PENDING",
                    "resigned": 0,
                }
            ],
            seed_bytes=b"demo-approved-seed",
            source_frontier=b"demo-frontier",
        )
        socket.socket = blocked_socket
        try:
            plan = plan_migration(store, work, observed_at="2026-09-11T19:30:00-05:00")
            result = run_migration(plan)
            with closing(open_active_readonly(store)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                status = connection.execute(
                    "SELECT migration_status FROM signed_objects WHERE object_id='future-demo'"
                ).fetchone()[0]
        finally:
            socket.socket = original_socket

    report = {
        "result": "PASS",
        "scope": "LOCAL_PYTHON_SQLITE_POSIX_MIGRATION_REHEARSAL_ONLY",
        "activeGeneration": result.active_generation,
        "activeStoreVersion": version,
        "unknownMandatoryStatus": status,
        "oldGenerationRetained": result.old_generation_retained,
        "egressAttempts": egress_attempts,
        "nativeBuildExecuted": False,
        "deviceVerified": False,
        "physicalPowerLossTested": False,
        "g9Qualified": False,
        "publicNetworkExecuted": False,
        "realCrdtMigrationExecuted": False,
        "productQualified": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
