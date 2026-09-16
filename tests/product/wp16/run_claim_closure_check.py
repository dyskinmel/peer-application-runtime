#!/usr/bin/env python3
"""Registered runner for the WP16 local fail-closed claim evaluator."""
from __future__ import annotations
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from harness.common import atomic_json
from tools.test_runner import RecordedResult

TEST_NAME = "tests.product.wp16.test_claim_closure"


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromName(TEST_NAME)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    cases = result.cases
    ok = result.wasSuccessful() and bool(cases) and all(c["status"] == "PASS" for c in cases)
    dest = os.environ.get("HARNESS_RESULT_PATH")
    if dest:
        nonce = os.environ.get("HARNESS_NONCE")
        if not nonce:
            print("HARNESS_NONCE is required when HARNESS_RESULT_PATH is set", file=sys.stderr)
            return 2
        atomic_json(Path(dest), {"schema_version": 1, "nonce": nonce, "cases": cases})
    print(json.dumps({
        "result": "PASS" if ok else "FAIL",
        "cases": len(cases),
        "scope": "LOCAL_FAIL_CLOSED_CLAIM_EVALUATOR_NOT_PRODUCT_QUALIFICATION",
        "product_qualified": False,
    }, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
