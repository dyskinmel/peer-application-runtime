#!/usr/bin/env python3
"""Finite local Blob binding tests; no network or production promotion."""
from __future__ import annotations
import argparse, os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for path in ['', 'experiments/blob-store', 'experiments/auth-store', 'experiments/space-auth', 'experiments/g0-crypto', 'experiments/g0-store', 'experiments/g0-wire', 'tests/product/auth-store', 'tests/product/space-auth', 'tests/product/blob-store']:
    sys.path.insert(0,str(ROOT/path))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'bindings':'test_blob_bindings','commit':'test_blob_commit','recovery':'test_blob_recovery','incoming':'test_incoming','faults':'test_blob_faults'}
def suite(group='all'):
    names=GROUPS.values() if group=='all' else [GROUPS[group]]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names if (ROOT/'tests/product/blob-store'/(n+'.py')).exists())
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=ap.parse_args()
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases})
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
