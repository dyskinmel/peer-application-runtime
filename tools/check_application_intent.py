#!/usr/bin/env python3
"""Exact durable intent tests; local POSIX and synthetic transaction contracts only."""
import argparse,json,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/application-intent',ROOT/'tests/product/fetch-owner',ROOT/'tests/product/fetch-bridge',ROOT/'tests/product/document-apply',ROOT/'tests/product/secure-fetch',ROOT/'tests/product/secure-transport',ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in(ROOT/'experiments').iterdir()if p.is_dir()]:sys.path.insert(0,str(p))
from tools.test_runner import RecordedResult
from harness.common import atomic_json
GROUPS={'journal':'test_intent_journal','coordinator':'test_intent_coordinator','owner-regression':'test_owner_deadline_regression','process':'test_intent_process'}
def flatten(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):yield from flatten(t)
  else:yield t

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--suite',choices=['all',*GROUPS],default='all');a.add_argument('--list',action='store_true');args=a.parse_args()
 if os.name!='posix':print(json.dumps({'result':'BLOCKED','executed_cases':0,'reason':'POSIX_REQUIRED'}));return 78
 s=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g])for g in(GROUPS if args.suite=='all'else[args.suite]));ids=sorted(t.id()for t in flatten(s))
 if args.list:print(json.dumps(ids,indent=2));return 0
 r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(s);cases=r.cases
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
 actual=[t['id']for t in cases];ok=r.wasSuccessful()and ids==sorted(actual)and len(actual)==len(set(actual))and all(t['status']=='PASS'for t in cases)
 print(json.dumps({'result':'PASS'if ok else'FAIL','registered_cases':len(ids),'executed_cases':len(actual),'real_core_executed':False,'product_qualified':False,'apply_wire_exposed':False}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
