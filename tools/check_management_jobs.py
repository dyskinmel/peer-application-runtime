#!/usr/bin/env python3
"""Bounded owner management job contract tests, not product qualification."""
import argparse, os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_host_snapshot import GROUPS as PREVIOUS_GROUPS
for name in ('experiments/host-management-jobs','tests/product/host-management-jobs'):
    sys.path.insert(0,str(ROOT/name))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_jobs_contract','lifecycle':'test_jobs_lifecycle','audit':'test_jobs_audit','faults':'test_jobs_faults','integration':'test_jobs_integration'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all' else [group]))
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=ap.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
