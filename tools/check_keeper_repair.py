#!/usr/bin/env python3
"""Explicit local object repair, not production or native qualification."""
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_gc import GROUPS as GC_GROUPS
for p in ('experiments/keeper-repair','tests/product/keeper-repair'):sys.path.insert(0,str(ROOT/p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_repair_contract','lifecycle':'test_repair_lifecycle','audit':'test_repair_audit','faults':'test_repair_faults'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all' else [group]))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=p.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
