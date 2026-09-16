#!/usr/bin/env python3
"""Private AF_UNIX read-only service checks; no public-network qualification."""
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_repair import GROUPS as REPAIR_GROUPS
for p in ('experiments/keeper-service','tests/product/keeper-service'):sys.path.insert(0,str(ROOT/p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_service_contract','lifecycle':'test_service_lifecycle','recovery':'test_service_recovery','faults':'test_service_faults','hardening':'test_service_hardening'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all' else [group]))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=p.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
