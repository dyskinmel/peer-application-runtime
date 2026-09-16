#!/usr/bin/env python3
"""Exact-ID causal read contracts. Private IPC only; no CRDT/core claim."""
import argparse,json,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/causal-exchange',ROOT/'tests/product/sync-inbox',ROOT/'tests/product/shared-document',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from tools.test_runner import RecordedResult
from harness.common import atomic_json
GROUPS={'source':'test_contract.SourceTests','protocol':'test_contract.ProtocolTests','socket':'test_socket.SocketTests','process':'test_process.ProcessTests','hardening':'test_hardening.HardeningTests'}
def flat(s):
 for x in s:
  if isinstance(x,unittest.TestSuite):yield from flat(x)
  else:yield x

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--suite',choices=['all',*GROUPS],default='all');a.add_argument('--list',action='store_true');ns=a.parse_args()
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if ns.suite=='all' else [ns.suite]));ids=sorted(t.id() for t in flat(suite));assert len(set(ids))==len(ids)
 if ns.list:print(json.dumps(ids));return 0
 r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite)
 assert sorted(c['id'] for c in r.cases)==ids
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
 good=r.wasSuccessful() and all(c['status']=='PASS' for c in r.cases)
 print(json.dumps({'result':'PASS' if good else 'FAIL','cases':len(ids),'real_core_executed':False,'applied':False,'scope':'PRIVATE_CAUSAL_READ_AND_EXPLICIT_PENDING_RECEIVE'}));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
