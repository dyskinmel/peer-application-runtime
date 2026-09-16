#!/usr/bin/env python3
"""Focused mutation witnesses in disposable copies, NEVER in the source tree.

Exit 0 means these exact three safety regressions were detected and the original
109-case suite passed. It is not a global mutation score or independent review.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
MUTATIONS=[
 ('accept-local-view','product/wp09/par_secure_fetch/dependencies.py',
  "require(current == self.local_revision, 'LOCAL_VIEW_CHANGED')","pass  # deliberately remove accept-time view check",'planner','test_accept_rechecks_local_view'),
 ('original-inquiry-intent','product/runtime_read/fetch.py',
  "require(self._unresolved_intent is None\n                or self._unresolved_intent == (operation_id, expected_revision),\n                'ORIGINAL_OPERATION_REQUIRED')","pass  # deliberately accept an unrelated inquiry",'application-contract','test_unknown_inquiry_must_use_original_id'),
 ('typed-full-context','product/wp11/src/fetch-observation.ts',
  "check(canonical(pin)===canonical(expected),'pinned context','FETCH_PIN_MISMATCH')","check(true,'pinned context','FETCH_PIN_MISMATCH')",'node','fetch.bridge.node.pin_planDigest')]
IGNORE={'.git','.harness','release','node_modules','__pycache__','.pytest_cache'}
def files(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()and not any(x in IGNORE for x in p.relative_to(root).parts)and p.suffix!='.pyc'}
def run(root,suite):
    env=os.environ.copy();env.pop('HARNESS_RESULT_PATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    return subprocess.run([sys.executable,'-I','-S','-B',str(root/'tools/check_fetch_bridge.py'),'--suite',suite],cwd=root,env=env,text=True,capture_output=True,timeout=120)
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    output=args.output.resolve()
    if output.is_relative_to(ROOT):raise ValueError('Write mutation evidence outside source root')
    output.mkdir(parents=True,exist_ok=True);before=files(ROOT);results=[]
    for name,path,old,new,suite,witness in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix='par-bridge-mutation-')as tmp:
            copy=Path(tmp)/'source';shutil.copytree(ROOT,copy,ignore=lambda d,n:[x for x in n if x in IGNORE or x.endswith('.pyc')])
            file=copy/path;text=file.read_text()
            if text.count(old)!=1:raise ValueError('Mutation target changed: '+name)
            file.write_text(text.replace(old,new,1))
            if path.endswith('.ts'):
                build=subprocess.run([shutil.which('tsc')or'tsc','-p',str(copy/'product/wp11/tsconfig.json'),'--outDir',str(copy/'product/wp11/lib')],capture_output=True,text=True,timeout=45)
                if build.returncode:raise RuntimeError('Mutated build failed rather than assertion: '+build.stderr+build.stdout)
            cp=run(copy,suite);(output/(name+'.stdout')).write_text(cp.stdout);(output/(name+'.stderr')).write_text(cp.stderr)
            detected=cp.returncode==1 and witness in cp.stderr and 'AssertionError'in cp.stderr
            results.append({'mutation':name,'suite':suite,'witness':witness,'exit_code':cp.returncode,'detected_by_assertion':detected})
    cp=run(ROOT,'all');(output/'normal.stdout').write_text(cp.stdout);(output/'normal.stderr').write_text(cp.stderr)
    unchanged=before==files(ROOT);good=unchanged and cp.returncode==0 and all(x['detected_by_assertion']for x in results)
    report={'result':'PASS'if good else'FAIL','scope':'THREE_TARGETED_MUTATIONS_ONLY','mutations':results,'original_unchanged':unchanged,'normal_exit':cp.returncode,'independent_review':'NOT_RUN','real_core_executed':False}
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
