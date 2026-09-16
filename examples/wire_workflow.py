#!/usr/bin/env python3
"""Synchronous H0 + G0-WIRE-LOCAL verification and non-replaying resume."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.lifecycle import begin,checkpoint,resume,loop_state
from harness.execution import run_session,verify_run
from harness.snapshot import snapshot

def main():
    steps=[]
    for tid,next_action in [('H0-SELFTEST','Run G0-WIRE-LOCAL on this exact source.'),('G0-WIRE-LOCAL','Read plan/NEXT_G0_STORE.ja.md; start G0-STORE without waiting for Rust/native wire qualification.')]:
        s=begin(ROOT,tid);r=run_session(ROOT,s['id']);v=verify_run(ROOT,r['id'])
        if not v['valid']:
            print(json.dumps({'task':tid,'run':r,'verification':v},ensure_ascii=False,indent=2));return 1
        c=checkpoint(ROOT,s['id'],next_action);re=resume(ROOT,c['id'])
        if re['state']!='READY':print(json.dumps(re,indent=2));return 1
        steps.append({'task':tid,'session_id':s['id'],'run_id':r['id'],'checkpoint_id':c['id'],'verification':v,'resume':re,'loop':loop_state(ROOT,s['id']),'case_count':sum(len(x['expected']) for x in r['checks'])})
    print(json.dumps({'scope':'H0_AND_LOCAL_WIRE_EXPERIMENT_ONLY','source_digest':snapshot(ROOT)['digest'],'steps':steps,'product_gates_promoted':False,'independent_review':'NOT_RUN'},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
