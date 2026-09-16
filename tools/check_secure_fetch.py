#!/usr/bin/env python3
"""Exact-ID secure fetch tests; local candidate persistence, not CRDT apply."""
import argparse,json,os,shutil,ssl,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/secure-fetch',ROOT/'tests/product/secure-transport',ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from tools.test_runner import RecordedResult
from harness.common import atomic_json
GROUPS={'plan':'test_plan','resume':'test_resume','client':'test_client','process':'test_process_fetch'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g])for g in (GROUPS if group=='all'else[group]))
def flat(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from flat(t)
        else:yield t

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--list',action='store_true');a.add_argument('--suite',choices=['all',*GROUPS],default='all');ns=a.parse_args();tests=suite(ns.suite);expected=sorted(t.id()for t in flat(tests))
    if ns.list:print(json.dumps(expected,indent=2));return 0
    if sys.version_info<(3,11)or not ssl.HAS_TLSv1_3 or shutil.which('openssl')is None:
        print(json.dumps({'result':'BLOCKED','reason':'TLS_PROVIDER_UNAVAILABLE','executed_cases':0}));return 78
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(tests)
    if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    ids=[c['id']for c in r.cases];good=bool(ids)and sorted(ids)==expected and len(ids)==len(set(ids))and all(c['status']=='PASS'for c in r.cases)and r.wasSuccessful()
    print(json.dumps({'result':'PASS'if good else'FAIL','registered_cases':len(expected),'executed_cases':len(ids),'crdt_applied':False,'independent_review':'NOT_RUN'}));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
