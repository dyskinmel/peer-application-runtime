#!/usr/bin/env python3
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from harness.common import atomic_json,read_json
from harness.planner import validate_catalog,load_tasks

def main():
    cases=[]
    for cid,fn in [('plan.references',lambda:load_tasks(ROOT)),('plan.coverage',lambda:validate_catalog(ROOT)),('plan.local_first',lambda:load_tasks(ROOT))]:
        try:fn();status='PASS'
        except Exception as e:print(cid,str(e));status='FAIL'
        cases.append({'id':cid,'status':status})
    state=read_json(ROOT/'plan/product-state.json')
    ok=state['native_runtime']=='NOT_STARTED' and state['runtime_tests_executed']==0 and not state['qualified_profiles'] and all(x=='NOT_RUN' for x in state['gates'].values())
    cases.append({'id':'plan.product_unqualified','status':'PASS' if ok else 'FAIL'})
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ['HARNESS_NONCE'],'cases':cases})
    print(cases)
    return 0 if all(c['status']=='PASS' for c in cases) else 1
if __name__=='__main__':raise SystemExit(main())
