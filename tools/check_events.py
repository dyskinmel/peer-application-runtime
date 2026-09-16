#!/usr/bin/env python3
"""Local encrypted event/cursor and coalescing contracts. No native/remote qualification."""
import argparse,json,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/wp10',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'crash':'test_event_crash.CrashTests','snapshot':'test_subscriptions.SubscriptionTests','presence':'test_subscriptions.PresenceTests','hardening':'test_events_hardening.HardeningTests','contract':'test_events.ContractTests','cursor':'test_events.CursorTests','storage':'test_events.StorageTests'}
def flatten(s):
 for x in s:
  if isinstance(x,unittest.TestSuite):yield from flatten(x)
  else:yield x
def inventory(group):return sorted(x.id() for x in flatten(unittest.defaultTestLoader.loadTestsFromName(GROUPS[group])))
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*GROUPS],default='all');ap.add_argument('--list',action='store_true');ns=ap.parse_args();groups=list(GROUPS) if ns.suite=='all' else [ns.suite]
 ids=sum([inventory(g) for g in groups],[])
 if len(ids)!=len(set(ids)):raise RuntimeError('duplicate IDs')
 if ns.list:print(json.dumps(ids));return 0
 cases=[]
 for g in groups:
  r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]));cases+=r.cases
 if sorted(x['id'] for x in cases)!=sorted(ids):raise RuntimeError('ID mismatch')
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
 good=bool(cases) and all(x['status']=='PASS' for x in cases)
 print(json.dumps({'result':'PASS' if good else 'FAIL','cases':len(cases),'scope':'LOCAL_ENCRYPTED_EVENTS_AND_SDK_CONTRACTS_ONLY','product_qualified':False}));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
