#!/usr/bin/env python3
"""Private upload candidate tests; no production network qualification."""
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_service import GROUPS as SERVICE_GROUPS
for p in ('experiments/keeper-upload','tests/product/keeper-upload'):sys.path.insert(0,str(ROOT/p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_upload_contract','spool':'test_upload_spool','service':'test_upload_service','faults':'test_upload_faults'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all' else [group]))
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=ap.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
