#!/usr/bin/env python3
"""Exact external-pin checks; local files and synthetic SQLite contracts only."""
import argparse,json,os,sys,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools import check_application_intent # Reuse the existing pinned bootstrap.
from tools.test_runner import RecordedResult
from harness.common import atomic_json
GROUPS={'store':'test_pin_anchor','application':'test_anchored_application','process':'test_anchor_process'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g])for g in(GROUPS if group=='all' else [group]))
def ids(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from ids(t)
        else:yield t.id()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*GROUPS],default='all');ap.add_argument('--list',action='store_true');a=ap.parse_args()
    if os.name!='posix':print(json.dumps({'result':'BLOCKED','executed_cases':0,'reason':'POSIX_REQUIRED'}));return 78
    s=suite(a.suite);expected=sorted(ids(s))
    if a.list:print(json.dumps(expected,indent=2));return 0
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(s);actual=[c['id']for c in r.cases]
    if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    ok=r.wasSuccessful()and bool(expected)and expected==sorted(actual)and len(set(actual))==len(actual)and all(c['status']=='PASS'for c in r.cases)
    print(json.dumps({'result':'PASS'if ok else'FAIL','registered_cases':len(expected),'executed_cases':len(actual),'real_core_executed':False,'apply_wire_exposed':False,'hardware_rollback_protected':False,'product_qualified':False}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
