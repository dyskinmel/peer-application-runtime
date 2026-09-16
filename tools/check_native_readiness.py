#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'handoff/native_readiness'

def load(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('--json',action='store_true'); a=p.parse_args(argv)
 errors=[]; goals=[]
 for name in ('g0-actor','g0-wire','g0-store'):
  cp=BASE/'contracts'/f'{name}.json'; rp=BASE/'corpora'/f'{name}.json'
  try: c=load(cp); r=load(rp)
  except Exception as e: errors.append(f'{name}:LOAD:{type(e).__name__}'); continue
  if c.get('product_qualified') is not False or r.get('product_qualified') is not False: errors.append(f'{name}:PRODUCT_PROMOTION')
  if r.get('native_qualified') is not False: errors.append(f'{name}:NATIVE_PROMOTION')
  for row in r.get('bindings',[]):
   try:
    path=ROOT/row['path']; actual=sha(path)
    if actual!=row['sha256']: errors.append(f"{name}:HASH:{row['path']}")
   except Exception as e: errors.append(f'{name}:BINDING:{type(e).__name__}')
  goals.append({'goal':c.get('goal'),'status':c.get('status'),'native_qualified':bool(c.get('native_qualified',False) or c.get('device_qualified',False))})
 out={'result':'PASS_LOCAL_READINESS' if not errors else 'FAIL','errors':errors,'goals':goals,'native_qualified':False,'product_qualified':False}
 print(json.dumps(out,ensure_ascii=False,indent=2) if a.json else out['result'])
 return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())
