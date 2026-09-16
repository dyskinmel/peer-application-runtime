#!/usr/bin/env python3
"""Exact-identity Node/WebCrypto/POSIX draft checks; not browser IndexedDB qualification."""
from __future__ import annotations
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.common import clean_env,atomic_json
from tools.check_reference_presenter import build

def inventory():
 env=clean_env();env['PAR_ROOT']=str(ROOT)
 cp=subprocess.run(['node',str(ROOT/'tests/product/wp11/durable/run.mjs'),'--list'],cwd=ROOT,env=env,text=True,capture_output=True,check=True,timeout=15)
 ids=json.loads(cp.stdout)
 if len(ids)!=len(set(ids)):raise RuntimeError('duplicate draft test identity')
 return sorted(ids)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--list',action='store_true');a=ap.parse_args()
 if a.list:print(json.dumps(inventory()));return 0
 with tempfile.TemporaryDirectory(prefix='par-private-draft-check-') as temp:
  dest=Path(temp);compiler=build(dest);result=dest/'result.json';env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_PRESENTER_BUILD=str(dest),HARNESS_RESULT_PATH=str(result),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
  cp=subprocess.run([compiler['node'],str(ROOT/'tests/product/wp11/durable/run.mjs')],cwd=ROOT,env=env,text=True,capture_output=True,timeout=90)
  print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr)
  if not result.exists():raise RuntimeError('missing draft test result')
  data=json.loads(result.read_text());ids=[c['id'] for c in data['cases']]
  if sorted(ids)!=inventory() or len(ids)!=len(set(ids)) or data['nonce']!=env['HARNESS_NONCE']:raise RuntimeError('draft identity/nonce mismatch')
  if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),data)
  good=cp.returncode==0 and data['cases'] and all(c['status']=='PASS' for c in data['cases'])
  print(json.dumps({'scope':'PRIVATE_DRAFT_NODE_FILE_CANDIDATE_ONLY','result':'PASS' if good else 'FAIL','cases':len(ids),'compiler':compiler},indent=2));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
