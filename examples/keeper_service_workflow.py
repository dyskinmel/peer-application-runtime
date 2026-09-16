#!/usr/bin/env python3
"""Run one/all local lanes, or independently re-verify saved checkpoint summaries."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.lifecycle import begin,checkpoint,resume,loop_state
from harness.execution import run_session,verify_run
from harness.snapshot import snapshot
from harness.common import atomic_json,read_json
TASKS=['H0-SELFTEST','G0-WIRE-LOCAL','G0-STORE-LOCAL','G0-CRYPTO-LOCAL','SPACE-AUTH-LOCAL','AUTH-STORE-LOCAL','BLOB-STORE-LOCAL','BLOB-MANIFEST-LOCAL','RECOVERY-CLOSURE-LOCAL','KEEPER-RETENTION-LOCAL','KEEPER-GC-LOCAL','KEEPER-REPAIR-LOCAL','KEEPER-SERVICE-LOCAL']
INDEX=ROOT/'.harness/keeper-service-workflow-index.json'
def step(tid):
    s=begin(ROOT,tid);r=run_session(ROOT,s['id']);v=verify_run(ROOT,r['id'])
    if not v['valid']:raise RuntimeError(json.dumps({'task':tid,'run_id':r['id'],'verification':v}))
    cp=checkpoint(ROOT,s['id'],'Read plan/NEXT_KEEPER_SERVICE_UPLOAD.ja.md. Private Linux read IPC is implemented; upload/mutation service, public/native transport, CRDT and writable recovery remain unverified.')
    re=resume(ROOT,cp['id'])
    if re['state']!='READY':raise RuntimeError(json.dumps(re))
    return {'task':tid,'session_id':s['id'],'run_id':r['id'],'checkpoint_id':cp['id'],'verification':v,'resume':re,'loop':loop_state(ROOT,s['id']),'case_count':sum(len(x['expected']) for x in r['checks'])}
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--only',choices=TASKS);ap.add_argument('--resume-summary',action='store_true');args=ap.parse_args()
    state=read_json(INDEX) if INDEX.exists() else {'schema_version':1,'steps':{}}
    if not args.resume_summary:
        for tid in ([args.only] if args.only else TASKS):
            state['steps'][tid]=step(tid);atomic_json(INDEX,state)
            print('VERIFIED '+tid, file=sys.stderr,flush=True)
    checked=[];missing=[]
    for tid in (TASKS if args.resume_summary or not args.only else [args.only]):
        if tid not in state['steps']:missing.append(tid);continue
        row=dict(state['steps'][tid]);row['verification']=verify_run(ROOT,row['run_id']);row['resume']=resume(ROOT,row['checkpoint_id'])
        row['valid']=row['verification']['valid'] and row['verification'].get('task_id')==tid and row['resume']['state']=='READY' and row['resume'].get('task_id')==tid
        checked.append(row)
    good=not missing and bool(checked) and all(r['valid'] for r in checked)
    print(json.dumps({'scope':'LOCAL_EXPERIMENTS_ONLY','result':'PASS' if good else 'INCOMPLETE_OR_STALE','source_digest':snapshot(ROOT)['digest'],'steps':checked,'missing':missing,'product_gates_promoted':False,'independent_review':'NOT_RUN'},ensure_ascii=False,indent=2))
    return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
