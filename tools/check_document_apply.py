#!/usr/bin/env python3
"""Exact-ID application/storage contracts; NOT real-core qualification."""
from pathlib import Path
import argparse,json,os,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/document-apply',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from harness.common import atomic_json,clean_env
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_apply_contract.ContractTests','storage':'test_apply_storage.StorageTests','inbox':'test_apply_inbox.InboxTests','hardening':'test_apply_hardening.HardeningTests','crash':'test_apply_crash.CrashTests','migration':'test_apply_migration.MigrationTests','node':None}
def flatten(s):
 for x in s:
  if isinstance(x,unittest.TestSuite):yield from flatten(x)
  else:yield x

def inventory(group):
 if group!='node':return sorted(x.id() for x in flatten(unittest.defaultTestLoader.loadTestsFromName(GROUPS[group])))
 return sorted(json.loads(subprocess.check_output(['node',str(ROOT/'tests/product/document-apply/materializer_contracts.mjs'),'--list'],env=clean_env(),cwd=ROOT,text=True,timeout=15)))
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--suite',choices=['all',*GROUPS],default='all');a.add_argument('--list',action='store_true');ns=a.parse_args()
 groups=list(GROUPS) if ns.suite=='all' else [ns.suite];ids=sum([inventory(g) for g in groups],[])
 if len(ids)!=len(set(ids)):raise RuntimeError('duplicate test identity')
 if ns.list:print(json.dumps(sorted(ids)));return 0
 results=[]
 for g in groups:
  if g!='node':
   result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]));results+=result.cases
  else:
   with tempfile.TemporaryDirectory(prefix='par-shared-check-') as p:
    dest=Path(p)/'result.json';env=clean_env();env.update(PAR_NODE_RESULT=str(dest),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
    cp=subprocess.run(['node',str(ROOT/'tests/product/document-apply/materializer_contracts.mjs')],capture_output=True,text=True,cwd=ROOT,env=env,timeout=30)
    print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr);data=json.loads(dest.read_text())
    if data['nonce']!=env['HARNESS_NONCE']:raise RuntimeError('nonce mismatch')
    if cp.returncode and all(x['status']=='PASS' for x in data['cases']):raise RuntimeError('returncode/claims conflict')
    results+=data['cases']
 actual=[x['id'] for x in results]
 if sorted(actual)!=sorted(ids) or len(actual)!=len(set(actual)):raise RuntimeError('identity set mismatch')
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':results})
 good=bool(results) and all(x['status']=='PASS' for x in results)
 print(json.dumps({'result':'PASS' if good else 'FAIL','cases':len(results),'scope':'SYNTHETIC_SEMANTICS_REAL_CRYPTO_AND_ATOMIC_APPLICATION_STORE','real_core_executed':False,'product_qualified':False}));return 0 if good else 1
if __name__=='__main__':sys.exit(main())
