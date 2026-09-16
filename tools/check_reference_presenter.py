#!/usr/bin/env python3
"""Compile the portable Presenter and execute exact Node test identities; no UI/runtime proof."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.common import atomic_json,clean_env
GROUPS=('contract','states','stories','commands','draft','locale','hardening','adapter','types')

def build(destination:Path)->dict:
    node=shutil.which('node');tsc=shutil.which('tsc')
    if not node or not tsc:raise RuntimeError('REQUIRED_TOOL_MISSING: node and tsc must be installed; no automatic downloads')
    args=[tsc,'-p',str(ROOT/'product/wp11/tsconfig.json'),'--outDir',str(destination)]
    cp=subprocess.run(args,cwd=ROOT,env=clean_env(),text=True,capture_output=True,timeout=45)
    if cp.returncode:raise RuntimeError('TYPESCRIPT_BUILD_FAILED\n'+cp.stdout+cp.stderr)
    (destination/'package.json').write_text('{"type":"module"}\n')
    shipped=ROOT/'product/wp11/lib'
    actual={p.name:p.read_bytes() for p in destination.iterdir() if p.is_file()}
    expected={p.name:p.read_bytes() for p in shipped.iterdir() if p.is_file()}
    if actual!=expected:raise RuntimeError('SHIPPED_BUILD_MISMATCH: review and rebuild the generated artifacts')
    compiler=Path(tsc).resolve();details={'node':str(Path(node).resolve()),'tsc':str(compiler),'tsc_sha256':hashlib.sha256(compiler.read_bytes()).hexdigest(),'version':subprocess.check_output([tsc,'--version'],text=True,env=clean_env(),timeout=5).strip()}
    # Record actual compiler JS payload in addition to the launcher (not a supply-chain attestation).
    details['compiler_js']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((compiler.parent.parent/'lib').glob('*tsc*.js'))]
    return details

def inventory(group='all')->list[str]:
    if group=='types':return ['presenter.types.contracts']
    env=clean_env();env['PAR_ROOT']=str(ROOT)
    cp=subprocess.run([shutil.which('node') or 'node',str(ROOT/'tests/product/wp11/run.mjs'),'--list','--group',group],cwd=ROOT,env=env,capture_output=True,text=True,timeout=15,check=True)
    values=json.loads(cp.stdout)
    return sorted(values+(['presenter.types.contracts'] if group=='all' else []))

def execute(group='all')->tuple[list[dict],dict]:
    cases=[]
    with tempfile.TemporaryDirectory(prefix='par-presenter-') as tmp:
        dest=Path(tmp);compiler=build(dest)
        if group!='types':
            result=dest/'node-result.json';env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_PRESENTER_BUILD=str(dest),PAR_NODE_RESULT=str(result),HARNESS_NONCE=os.environ.get('HARNESS_NONCE','standalone'))
            cp=subprocess.run([compiler['node'],str(ROOT/'tests/product/wp11/run.mjs'),'--group',group],cwd=ROOT,env=env,capture_output=True,text=True,timeout=75)
            print(cp.stdout,end='');print(cp.stderr,end='',file=sys.stderr)
            if not result.exists():raise RuntimeError('MISSING_NODE_RESULT')
            obj=json.loads(result.read_text());cases=obj['cases']
            if obj.get('nonce')!=env['HARNESS_NONCE']:raise RuntimeError('RESULT_NONCE_MISMATCH')
            if cp.returncode==0 and any(c['status']!='PASS' for c in cases):raise RuntimeError('INCONSISTENT_NODE_RESULT')
            if cp.returncode!=0 and all(c['status']=='PASS' for c in cases):raise RuntimeError('NODE_PROCESS_FAILED')
        if group in ('all','types'):
            cp=subprocess.run([compiler['tsc'],'--noEmit','--target','ES2022','--module','NodeNext','--moduleResolution','NodeNext','--strict','--exactOptionalPropertyTypes','--noUncheckedIndexedAccess',str(ROOT/'tests/product/wp11/type_contract.mts')],cwd=ROOT,env=clean_env(),capture_output=True,text=True,timeout=45)
            print(cp.stdout+cp.stderr,end='');cases.append({'id':'presenter.types.contracts','status':'PASS' if cp.returncode==0 else 'FAIL'})
    ids=[c['id'] for c in cases]
    if len(ids)!=len(set(ids)) or sorted(ids)!=inventory(group):raise RuntimeError('CASE_IDENTITY_SET_MISMATCH')
    return cases,compiler

def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all',*GROUPS],default='all');p.add_argument('--list',action='store_true');args=p.parse_args()
    if args.list:print(json.dumps(inventory(args.suite)));return 0
    try:cases,compiler=execute(args.suite)
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as e:print(str(e),file=sys.stderr);return 1
    if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
    ok=bool(cases) and all(c['status']=='PASS' for c in cases)
    print(json.dumps({'scope':'PRESENTER_ONLY_NOT_RENDERED_UI_OR_CRDT','result':'PASS' if ok else 'FAIL','cases':len(cases),'compiler':compiler},indent=2))
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
