#!/usr/bin/env python3
"""Exact local native/provider handoff checks.

This checker validates the injected-provider contract, source shape and Node/Python
lifetime agreement. It intentionally does NOT require or claim a Swift/Rust build,
device Keychain behavior, rollback resistance, G9, or production qualification.
"""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/product/wp14'))
from tools.test_runner import RecordedResult
from harness.common import atomic_json,clean_env
GROUPS={
 'manifest':'test_manifest.ManifestTests',
 'handoff':'test_handoff.HandoffTests',
 'doctor':'test_doctor.DoctorTests',
 'fixture':'test_fixture.FixtureTests',
 'native':'test_native_sources.NativeSourceTests',
 'process':'test_process.ProcessTests',
}
NODE=ROOT/'tests/product/wp14/node_contracts.mjs';TYPE=ROOT/'tests/product/wp14/type_contract.mts';TYPE_ID='native-provider.node.types'

def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all'else[group]))
def flat(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from flat(t)
        else:yield t

def node_ids():
    cp=subprocess.run([shutil.which('node')or'node',str(NODE),'--list'],capture_output=True,text=True,timeout=15,check=True,env=clean_env())
    return sorted(json.loads(cp.stdout)+[TYPE_ID])
def inventory(group='all'):
    ids=[]
    if group!='node':ids.extend(t.id() for t in flat(suite(group)))
    if group in ('all','node'):ids.extend(node_ids())
    return sorted(ids)

def node_run():
    env=clean_env();cp=subprocess.run([shutil.which('node')or'node',str(NODE)],capture_output=True,text=True,timeout=30,env=env)
    print(cp.stderr,end='',file=sys.stderr)
    report=json.loads(cp.stdout);cases=report['cases'];good=bool(cases)and all(c['status']=='PASS'for c in cases)
    if (cp.returncode==0)!=good:raise RuntimeError('NODE_RESULT_EXIT_MISMATCH')
    tsc=shutil.which('tsc')or'tsc';tp=subprocess.run([tsc,'--noEmit','--target','ES2022','--module','NodeNext','--moduleResolution','NodeNext','--strict','--exactOptionalPropertyTypes','--noUncheckedIndexedAccess',str(TYPE)],capture_output=True,text=True,timeout=30,env=clean_env())
    print(tp.stdout+tp.stderr,end='');cases.append({'id':TYPE_ID,'status':'PASS'if tp.returncode==0 else'FAIL'})
    return cases

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*GROUPS,'node'],default='all');ap.add_argument('--list',action='store_true');a=ap.parse_args()
    if not a.list:
        if sys.version_info<(3,11) or os.name!='posix':
            print(json.dumps({'result':'BLOCKED','reason':'PYTHON311_POSIX_REQUIRED','executed_cases':0,'nativeBuildExecuted':False,'deviceVerified':False}));return 78
        if a.suite in ('all','node') and (shutil.which('node')is None or shutil.which('tsc')is None):
            print(json.dumps({'result':'BLOCKED','reason':'NODE_TYPESCRIPT_REQUIRED','executed_cases':0,'nativeBuildExecuted':False,'deviceVerified':False}));return 78
    try:
        expected=inventory(a.suite)
        if a.list:print(json.dumps(expected,indent=2));return 0
        cases=[];success=True
        if a.suite!='node':
            r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite));cases.extend(r.cases);success=r.wasSuccessful()
            if r.fixture_diagnostics:print(json.dumps({'fixture_diagnostics':r.fixture_diagnostics}),file=sys.stderr)
        if a.suite in ('all','node'):cases.extend(node_run())
        if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
        actual=[c['id']for c in cases];ok=success and bool(expected) and sorted(actual)==expected and len(actual)==len(set(actual)) and all(c['status']=='PASS'for c in cases)
        print(json.dumps({'result':'PASS'if ok else'FAIL','registered_cases':len(expected),'executed_cases':len(actual),'scope':'LOCAL_PROVIDER_HANDOFF_AND_SOURCE_SHAPE_ONLY','nativeBuildExecuted':False,'deviceVerified':False,'osProtectionProven':False,'realCoreExecuted':False,'publicNetworkExecuted':False,'productQualified':False}));return 0 if ok else 1
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
