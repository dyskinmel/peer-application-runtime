#!/usr/bin/env python3
"""Exact local Python/SQLite/POSIX migration rehearsal checks.

This checker verifies the read-only planner, verified backup, logical shadow,
atomic generation activation and real-process SIGKILL recovery matrix. It does
not run or claim Rust/native migration, device secure storage, physical power
loss, G9 qualification, real CRDT migration, public networking or production
readiness.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/product/wp14_migration"))

from harness.common import atomic_json
from tools.test_runner import RecordedResult

GROUPS = {
    "planner": "test_planner.PlannerTests",
    "backup": "test_backup.BackupTests",
    "shadow": "test_shadow.ShadowTests",
    "activation": "test_activation.ActivationTests",
    "process": "test_process.ProcessRecoveryTests",
}


def suite(group: str = "all") -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    names = GROUPS.values() if group == "all" else (GROUPS[group],)
    return unittest.TestSuite(loader.loadTestsFromName(name) for name in names)


def flatten(value: unittest.TestSuite):
    for test in value:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def inventory(group: str = "all") -> list[str]:
    return sorted(test.id() for test in flatten(suite(group)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", *GROUPS], default="all")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    expected = inventory(args.suite)
    if args.list:
        print(json.dumps(expected, indent=2))
        return 0
    if sys.version_info < (3, 11) or os.name != "posix":
        print(
            json.dumps(
                {
                    "result": "BLOCKED",
                    "reason": "PYTHON311_POSIX_REQUIRED",
                    "registered_cases": len(expected),
                    "executed_cases": 0,
                    "productQualified": False,
                }
            )
        )
        return 78

    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite(args.suite))
    cases = result.cases
    if result.fixture_diagnostics:
        print(json.dumps({"fixture_diagnostics": result.fixture_diagnostics}), file=sys.stderr)
    actual = [case["id"] for case in cases]
    ok = (
        result.wasSuccessful()
        and bool(expected)
        and sorted(actual) == expected
        and len(actual) == len(set(actual))
        and all(case["status"] == "PASS" for case in cases)
    )
    if os.environ.get("HARNESS_RESULT_PATH"):
        atomic_json(
            Path(os.environ["HARNESS_RESULT_PATH"]),
            {
                "schema_version": 1,
                "nonce": os.environ.get("HARNESS_NONCE", "standalone"),
                "cases": cases,
            },
        )
    print(
        json.dumps(
            {
                "result": "PASS" if ok else "FAIL",
                "registered_cases": len(expected),
                "executed_cases": len(actual),
                "scope": "LOCAL_PYTHON_SQLITE_POSIX_MIGRATION_REHEARSAL_ONLY",
                "sigkillProcessMatrixExecuted": args.suite in ("all", "process"),
                "nativeBuildExecuted": False,
                "deviceVerified": False,
                "physicalPowerLossTested": False,
                "g9Qualified": False,
                "realCrdtMigrationExecuted": False,
                "publicNetworkExecuted": False,
                "productQualified": False,
            },
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
