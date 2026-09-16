#!/usr/bin/env python3
"""Exact owner-loop, frame, TypeScript generation and real connected-process checks."""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys,tempfile,unittest,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/event-host',ROOT/'tests/product/wp10',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from harness.common import atomic_json,clean_env
from tools.test_runner import RecordedResult
GROUPS=('owner','socket','hardening','node','channel','integration','types','command-owner','command-socket','command-node','command-channel','command-integration','command-types','client-node','client-integration','client-view','client-types')
PY_GROUPS={'owner':'test_host.HostTests','socket':'test_transport.TransportTests','hardening':'test_hardening.HardeningTests','command-owner':'test_commands.CommandTests','command-socket':'test_command_transport.CommandSocketTests'}
NODE_GROUPS={'node':'run.mjs','channel':'channel.mjs','integration':'integration.mjs','command-node':'commands.mjs','command-channel':'command_channel.mjs','command-integration':'command_integration.mjs','client-node':'client_lifecycle.mjs','client-integration':'client_integration.mjs','client-view':'client_view.mjs'}
TYPE_GROUPS={'types':('event-host.types.contract','tests/product/event-host/type_contract.mts'),'command-types':('event-command.types.contract','tests/product/event-host/command_types.mts'),'client-types':('event-client.types.contract','tests/product/event-host/client_types.mts')}
def flatten(s):
 for x in s:
  if isinstance(x,unittest.TestSuite):yield from flatten(x)
  else:yield x
def inventory(group):
 if group in PY_GROUPS:return sorted(x.id() for x in flatten(unittest.defaultTestLoader.loadTestsFromName(PY_GROUPS[group])))
 if group in TYPE_GROUPS:return [TYPE_GROUPS[group][0]]
 script=NODE_GROUPS[group]
 return sorted(json.loads(subprocess.check_output(['node',str(ROOT/'tests/product/event-host'/script),'--list'],cwd=ROOT,env=clean_env(),text=True,timeout=15)))
def build(dest):
 tsc=shutil.which('tsc');node=shutil.which('node')
 if not tsc or not node:raise RuntimeError('REQUIRED_TOOL_MISSING')
 cp=subprocess.run([tsc,'-p',str(ROOT/'product/wp10/tsconfig.json'),'--outDir',str(dest)],cwd=ROOT,env=clean_env(),text=True,capture_output=True,timeout=45)
 if cp.returncode:raise RuntimeError(cp.stdout+cp.stderr)
 (dest/'package.json').write_text('{"type":"module"}\n')
 actual={p.name:p.read_bytes() for p in dest.iterdir() if p.is_file() and p.name!='package.json'}
 shipped={p.name:p.read_bytes() for p in (ROOT/'product/wp10/lib').iterdir() if p.is_file()}
 if actual!=shipped:raise RuntimeError('SHIPPED_BUILD_MISMATCH')
 return {'node':node,'tsc':tsc,'tsc_sha256':hashlib.sha256(Path(tsc).resolve().read_bytes()).hexdigest()}
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all',*GROUPS],default='all');ap.add_argument('--list',action='store_true');a=ap.parse_args();groups=list(GROUPS) if a.suite=='all' else [a.suite]
 ids=sum((inventory(g)for g in groups),[])
 if len(ids)!=len(set(ids)):raise RuntimeError('DUPLICATE_TEST_IDS')
 if a.list:print(json.dumps(sorted(ids)));return 0
 cases=[]
 for group in groups:
  if group in PY_GROUPS:
   r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(unittest.defaultTestLoader.loadTestsFromName(PY_GROUPS[group]));cases+=r.cases
 if set(groups)-set(PY_GROUPS):
  with tempfile.TemporaryDirectory(prefix='par-sdk-test-') as tmp:
   dest=Path(tmp);compiler=build(dest)
   if set(groups)&{'client-view','client-types'}:
    from tools.check_reference_presenter import build as build_presenter
    with tempfile.TemporaryDirectory(prefix='par-client-presenter-') as ui_tmp:build_presenter(Path(ui_tmp))
   for group in groups:
    if group in PY_GROUPS:continue
    if group in TYPE_GROUPS:
     cp=subprocess.run([compiler['tsc'],'--noEmit','--target','ES2022','--module','NodeNext','--moduleResolution','NodeNext','--strict','--exactOptionalPropertyTypes','--noUncheckedIndexedAccess',str(ROOT/TYPE_GROUPS[group][1])],cwd=ROOT,env=clean_env(),capture_output=True,text=True,timeout=45)
     print(cp.stdout+cp.stderr,end='');cases.append({'id':TYPE_GROUPS[group][0],'status':'PASS' if cp.returncode==0 else 'FAIL'});continue
    result=dest/(group+'.json');env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_SDK_BUILD=str(dest),PAR_PYTHON=sys.executable,HARNESS_RESULT_PATH=str(result),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
    script=NODE_GROUPS[group]
    cp=subprocess.run([compiler['node'],str(ROOT/'tests/product/event-host'/script)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
    print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr)
    data=json.loads(result.read_text());rows=data['cases']
    if data['nonce']!=env['HARNESS_NONCE'] or (cp.returncode==0)!=all(x['status']=='PASS'for x in rows):raise RuntimeError('INVALID_TEST_RESULT')
    cases+=rows
 if sorted(x['id']for x in cases)!=sorted(ids):raise RuntimeError('TEST_ID_SET_MISMATCH')
 if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
 ok=bool(cases)and all(x['status']=='PASS'for x in cases);print(json.dumps({'result':'PASS'if ok else 'FAIL','scope':'LOCAL_OWNER_LOOP_PRECONNECTED_PRIVATE_IPC_NOT_PUBLIC_OR_NATIVE_QUALIFICATION','cases':len(cases)}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
