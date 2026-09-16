#!/usr/bin/env python3
"""Run finite auth/Store tests; product gates and real-host claims remain open."""
from __future__ import annotations
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth',ROOT/'experiments/auth-store',ROOT/'experiments/space-auth',ROOT/'experiments/g0-crypto',ROOT/'experiments/g0-wire',ROOT/'experiments/g0-store']:sys.path.insert(0,str(p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'commit':'test_commit_authority','persistence':'test_authority_persistence','schema':'test_schema_and_restore','faults':'test_auth_store_faults'}
def suite(group='all'):
    names=GROUPS.values() if group=='all' else [GROUPS[group]]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names if (ROOT/'tests/product/auth-store'/(n+'.py')).exists())
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases})
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
