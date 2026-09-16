#!/usr/bin/env python3
"""Fresh, synchronous local checks, evidence binding and checkpoint/resume."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.lifecycle import begin,checkpoint,resume,loop_state
from harness.execution import run_session,verify_run
from harness.snapshot import snapshot

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--include-wire',action='store_true');ap.add_argument('--include-store',action='store_true');args=ap.parse_args()
    tasks=['H0-SELFTEST']+(['G0-WIRE-LOCAL'] if args.include_wire else [])+(['G0-STORE-LOCAL'] if args.include_store else [])+['G0-CRYPTO-LOCAL']
    steps=[]
    for tid in tasks:
        s=begin(ROOT,tid);r=run_session(ROOT,s['id']);v=verify_run(ROOT,r['id'])
        if not v['valid']:
            print(json.dumps({'task':tid,'run':r,'verification':v},ensure_ascii=False,indent=2));return 1
        c=checkpoint(ROOT,s['id'],'Read plan/NEXT_SPACE_AUTH.ja.md; keep OD-01/G0 open. Revalidate native pins on any new host.')
        re=resume(ROOT,c['id'])
        if re['state']!='READY':print(json.dumps(re,indent=2));return 1
        steps.append({'task':tid,'session_id':s['id'],'run_id':r['id'],'checkpoint_id':c['id'],
            'verification':v,'resume':re,'loop':loop_state(ROOT,s['id']),
            'case_count':sum(len(x['expected']) for x in r['checks'])})
    print(json.dumps({'scope':'H0_AND_LOCAL_EXPERIMENTS_ONLY','source_digest':snapshot(ROOT)['digest'],'steps':steps,
        'product_gates_promoted':False,'independent_review':'NOT_RUN'},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
