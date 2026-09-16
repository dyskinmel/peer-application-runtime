#!/usr/bin/env python3
"""Exact owner/planner/typed-view checks. Synthetic apply is explicitly separate.

Node compiles and readback-compares the shipped JS/d.ts before contract tests.
No actual CRDT, browser, independent review or production qualification implied.
"""
from __future__ import annotations
import argparse,json,os,shutil,ssl,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/fetch-bridge',ROOT/'tests/product/document-apply',ROOT/'tests/product/secure-fetch',ROOT/'tests/product/secure-transport',ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in(ROOT/'experiments').iterdir()if p.is_dir()]:sys.path.insert(0,str(p))
from tools.test_runner import RecordedResult
from tools.check_reference_presenter import build
from harness.common import atomic_json,clean_env
GROUPS={'planner':'test_dependencies','controller':'test_fetch_controller','process':'test_bridge_process','application-contract':'test_application_delegation'}
ALL=(*GROUPS,'node')
TYPE_ID='fetch.bridge.types.contracts'

def suite(group):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all'else[group]))
def flat(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from flat(t)
        else:yield t

def node_ids():
    cp=subprocess.run([shutil.which('node')or'node',str(ROOT/'tests/product/fetch-bridge/node_contracts.mjs'),'--list'],capture_output=True,text=True,timeout=15,check=True,env=clean_env())
    return sorted(json.loads(cp.stdout)+[TYPE_ID])

def node_run():
    with tempfile.TemporaryDirectory(prefix='par-fetch-bridge-types-')as tmp:
        dest=Path(tmp);compiler=build(dest)
        fixture=dest/'fixture.json';result=dest/'node-result.json'
        cp=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'tests/product/fetch-bridge/export_fixture.py')],capture_output=True,text=True,timeout=20,env=clean_env())
        if cp.returncode:raise RuntimeError('PYTHON_FIXTURE_FAILED\n'+cp.stderr)
        json.loads(cp.stdout);fixture.write_text(cp.stdout)
        env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_PRESENTER_BUILD=str(dest),PAR_FETCH_FIXTURE=str(fixture),HARNESS_RESULT_PATH=str(result),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
        cp=subprocess.run([compiler['node'],str(ROOT/'tests/product/fetch-bridge/node_contracts.mjs')],capture_output=True,text=True,timeout=45,env=env)
        print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr)
        report=json.loads(result.read_text());cases=report['cases']
        if report.get('nonce')!=env['HARNESS_NONCE']:raise RuntimeError('RESULT_NONCE_MISMATCH')
        if bool(cp.returncode)==all(c['status']=='PASS'for c in cases):raise RuntimeError('NODE_RESULT_EXIT_MISMATCH')
        cp=subprocess.run([compiler['tsc'],'--noEmit','--target','ES2022','--module','NodeNext','--moduleResolution','NodeNext','--strict','--exactOptionalPropertyTypes','--noUncheckedIndexedAccess',str(ROOT/'tests/product/fetch-bridge/type_contract.mts')],capture_output=True,text=True,timeout=45,env=clean_env())
        print(cp.stdout+cp.stderr,end='');cases.append({'id':TYPE_ID,'status':'PASS'if cp.returncode==0 else'FAIL'})
        print(json.dumps({'compiler':compiler,'browser_executed':False}));return cases

def inventory(group):
    ids=[]
    if group!='node':ids.extend(t.id() for t in flat(suite(group)))
    if group in ('all','node'):ids.extend(node_ids())
    return sorted(ids)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*ALL],default='all');ap.add_argument('--list',action='store_true');args=ap.parse_args()
    if not args.list:
        reason=None
        if sys.version_info<(3,11)or not ssl.HAS_TLSv1_3 or shutil.which('openssl')is None:reason='TLS_PROVIDER_UNAVAILABLE'
        if args.suite in ('all','node')and(not shutil.which('node')or not shutil.which('tsc')):reason='TYPED_VIEW_TOOLCHAIN_UNAVAILABLE'
        if reason:
            print(json.dumps({'result':'BLOCKED','reason':reason,'executed_cases':0}));return 78
    try:
        ids=inventory(args.suite)
        if args.list:print(json.dumps(ids,indent=2));return 0
        cases=[];successful=True
        if args.suite!='node':
            r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(args.suite));cases.extend(r.cases);successful=r.wasSuccessful()
        if args.suite in('all','node'):cases.extend(node_run())
        if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
        actual=[t['id']for t in cases];good=bool(ids)and sorted(actual)==ids and len(actual)==len(set(actual))and all(t['status']=='PASS'for t in cases)and successful
        print(json.dumps({'result':'PASS'if good else'FAIL','registered_cases':len(ids),'executed_cases':len(actual),'real_core_executed':False,'browser_executed':False,'product_qualified':False,'synthetic_application_contract_included':args.suite in('all','application-contract')}));return 0 if good else 1
    except(OSError,ValueError,RuntimeError,subprocess.SubprocessError)as exc:
        print(str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
