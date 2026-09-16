#!/usr/bin/env python3
"""Bounded WP15 Harness-result integration regression; no product qualification."""
from __future__ import annotations
import json
import os
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))

from harness.common import atomic_json
from tools.test_runner import RecordedResult

TEST_NAME='tests.test_local_closure_sprint_a.Wp15HarnessResultContractTests'


def main() -> int:
    suite=unittest.defaultTestLoader.loadTestsFromName(TEST_NAME)
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite)
    cases=result.cases
    ok=(
        result.wasSuccessful()
        and bool(cases)
        and all(case['status']=='PASS' for case in cases)
    )
    dest=os.environ.get('HARNESS_RESULT_PATH')
    if dest:
        atomic_json(Path(dest),{
            'schema_version':1,
            'nonce':os.environ.get('HARNESS_NONCE','standalone'),
            'cases':cases,
        })
    print(json.dumps({
        'result':'PASS' if ok else 'FAIL',
        'cases':len(cases),
        'scope':'WP15_HARNESS_RESULT_CONTRACT_MAINTENANCE_ONLY',
        'product_qualified':False,
    },sort_keys=True))
    return 0 if ok else 1


if __name__=='__main__':
    raise SystemExit(main())
