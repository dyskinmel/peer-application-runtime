#!/usr/bin/env python3
"""Finite exact-ID real Store + TypeScript binding checks. No browser/CRDT claim."""
from __future__ import annotations
import argparse,contextlib,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/runtime-binding',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from harness.common import atomic_json,clean_env
from tools.test_runner import RecordedResult
from tools.check_reference_presenter import build

def flatten(s):
 for x in s:
  if isinstance(x,unittest.TestSuite):yield from flatten(x)
  else:yield x

def inventory(group):
 if group=='python':return sorted(x.id() for x in flatten(unittest.defaultTestLoader.loadTestsFromName('test_store_observation')))
 env=clean_env();env['PAR_ROOT']=str(ROOT)
 return sorted(json.loads(subprocess.check_output(['node',str(ROOT/'tests/product/runtime-binding/run.mjs'),'--list'],cwd=ROOT,env=env,text=True,timeout=15)))

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--suite',choices=['all','python','node'],default='all');a.add_argument('--list',action='store_true');args=a.parse_args();groups=['python','node'] if args.suite=='all' else [args.suite]
 ids=sum([inventory(g) for g in groups],[])
 if len(ids)!=len(set(ids)):raise RuntimeError('duplicate identity')
 if args.list:print(json.dumps(sorted(ids)));return 0
 cases=[]
 if 'python'in groups:
  result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(unittest.defaultTestLoader.loadTestsFromName('test_store_observation'));cases+=result.cases
 if 'node'in groups:
  with tempfile.TemporaryDirectory(prefix='par-runtime-read-') as temp:
   tmp=Path(temp);compiler=build(tmp);fixture=tmp/'observations.json';result=tmp/'node-result.json';env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_PRESENTER_BUILD=str(tmp),PAR_OBSERVATION_FIXTURE=str(fixture),HARNESS_RESULT_PATH=str(result),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
   cp=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'tests/product/runtime-binding/fixture.py')],cwd=ROOT,env=clean_env(),capture_output=True,text=True,timeout=30)
   if cp.returncode:raise RuntimeError('real Store fixture failed: '+cp.stderr)
   fixture.write_text(cp.stdout)
   cp=subprocess.run([compiler['node'],str(ROOT/'tests/product/runtime-binding/run.mjs')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60);print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr)
   data=json.loads(result.read_text())
   if data['nonce']!=env['HARNESS_NONCE']:raise RuntimeError('result nonce mismatch')
   if cp.returncode and all(x['status']=='PASS' for x in data['cases']):raise RuntimeError('process failed despite reported pass')
   cases+=data['cases']
 actual=[x['id'] for x in cases]
 if sorted(actual)!=sorted(ids) or len(actual)!=len(set(actual)):raise RuntimeError('case identity set mismatch')
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
 good=bool(cases) and all(x['status']=='PASS' for x in cases);print(json.dumps({'scope':'OWNER_READ_ONLY_OBSERVATION_AND_TYPED_BINDING_ONLY','cases':len(cases),'result':'PASS' if good else 'FAIL'}));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
