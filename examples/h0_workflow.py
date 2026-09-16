#!/usr/bin/env python3
"""Synchronous real H0 goal; requires only Python, produces local state/evidence."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from harness.lifecycle import begin,checkpoint,resume,loop_state
from harness.execution import run_session,verify_run
s=begin(ROOT,'H0-SELFTEST')
print('Session:',s['id'],flush=True)
r=run_session(ROOT,s['id'])
v=verify_run(ROOT,r['id'])
print(json.dumps(v,indent=2),flush=True)
if not v['valid']:raise SystemExit(1)
c=checkpoint(ROOT,s['id'],'Run G0-WIRE-LOCAL on the same candidate; full OD-02 remains open.')
print(json.dumps(resume(ROOT,c['id']),ensure_ascii=False,indent=2))
print(json.dumps(loop_state(ROOT,s['id']),ensure_ascii=False,indent=2))
