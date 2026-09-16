#!/usr/bin/env python3
"""Exact local resource/provider tests. Not native, 7-day soak or G8 qualification."""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_application_owner
from tools.test_runner import RecordedResult
from harness.common import atomic_json,clean_env
sys.path.insert(0,str(ROOT/'tests/product/provider-soak'))
GROUPS={'campaign':'test_campaign.CampaignTests','metrics':'test_metrics.MetricsTests',
        'providers':'test_providers.ProviderTests','process':'test_process.SoakProcessTests'}
NODE=ROOT/'tests/product/provider-soak/node_contracts.mjs'
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g])for g in(GROUPS if group=='all'else[group]))
def ids(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from ids(t)
        else:yield t.id()
def node_ids():
    cp=subprocess.run([shutil.which('node')or'node',str(NODE),'--list'],capture_output=True,text=True,timeout=15,check=True,env=clean_env())
    return sorted(json.loads(cp.stdout))
def inventory(group='all'):
    found=[]
    if group!='node':found.extend(ids(suite(group)))
    if group in('all','node'):found.extend(node_ids())
    return sorted(found)
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*GROUPS,'node'],default='all');ap.add_argument('--list',action='store_true');a=ap.parse_args()
    if not a.list and(not sys.platform.startswith('linux')or not Path('/proc/self/status').is_file()or shutil.which('node')is None):
        print(json.dumps({'result':'BLOCKED','executed_cases':0,'reason':'LINUX_PROC_NODE_REQUIRED'}));return 78
    try:
        expected=inventory(a.suite)
        if a.list:print(json.dumps(expected,indent=2));return 0
        cases=[];success=True
        if a.suite!='node':
            r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite));cases.extend(r.cases);success=r.wasSuccessful()
            if r.fixture_diagnostics:print(json.dumps({'fixture_diagnostics':r.fixture_diagnostics}),file=sys.stderr)
        if a.suite in('all','node'):
            cp=subprocess.run([shutil.which('node'),str(NODE)],capture_output=True,text=True,timeout=30,env=clean_env());print(cp.stderr,end='',file=sys.stderr)
            report=json.loads(cp.stdout);rows=report['cases'];good=bool(rows)and all(c['status']=='PASS'for c in rows)
            if(cp.returncode==0)!=good:raise RuntimeError('NODE_RESULT_EXIT_MISMATCH')
            cases.extend(rows)
        if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
        actual=[c['id']for c in cases];ok=success and bool(expected)and sorted(actual)==expected and len(actual)==len(set(actual))and all(c['status']=='PASS'for c in cases)
        print(json.dumps({'result':'PASS'if ok else'FAIL','registered_cases':len(expected),'executed_cases':len(actual),'real_core_executed':False,'browser_executed':False,'seven_day_soak_qualified':False,'product_qualified':False}));return 0 if ok else 1
    except(OSError,ValueError,RuntimeError,subprocess.SubprocessError)as e:print(str(e),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
