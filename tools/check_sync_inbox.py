#!/usr/bin/env python3
"""Exact-ID encrypted pending inbox tests; no real CRDT execution is claimed."""
from pathlib import Path
import sys,os,json,argparse,unittest
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/sync-inbox',ROOT/'tests/product/shared-document',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from tools.test_runner import RecordedResult
from harness.common import atomic_json
GROUPS={'receive':'test_inbox.ReceiveTests','dependencies':'test_inbox.DependencyTests','persistence':'test_inbox.PersistenceTests','hardening':'test_inbox.HardeningTests','crash':'test_crash.CrashTests'}
def flat(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):yield from flat(t)
  else:yield t

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all',*GROUPS],default='all');p.add_argument('--list',action='store_true');a=p.parse_args()
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if a.suite=='all' else [a.suite]))
 ids=sorted(t.id() for t in flat(suite));assert len(ids)==len(set(ids))
 if a.list:print(json.dumps(ids));return 0
 r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite);actual=[x['id'] for x in r.cases];assert sorted(actual)==ids
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
 print(json.dumps({'result':'PASS' if r.wasSuccessful() else 'FAIL','cases':len(ids),'real_core_executed':False,'scope':'LOCAL_SIGNED_ENCRYPTED_PENDING_INBOX'}));return 0 if r.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
