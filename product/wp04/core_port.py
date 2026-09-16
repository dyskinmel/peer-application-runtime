"""Finite owner-local child process adapter. Missing actual core is never PASS.

The approved package is trusted executable code, not an adversarial plugin.
Timeout/heap options do not constitute a WASM fuel meter or an OS sandbox.
"""
from __future__ import annotations
import json,os,subprocess,shutil,hashlib
from pathlib import Path
from harness.common import clean_env
from .contracts import SharedChangeError,canonical,require
WORKER=Path(__file__).with_name('core_worker.mjs')

class NodeCorePort:
    def __init__(self,manifest:Path,*,timeout=12):
        require(isinstance(manifest,Path) and manifest.is_absolute(),'CORE_MANIFEST_INVALID')
        require(type(timeout) in (int,float) and 0<timeout<=60,'INVALID_INPUT')
        self._manifest=manifest;self._timeout=timeout;self._node=shutil.which('node')
        self._runtime={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [WORKER,WORKER.with_name('automerge.mjs'),Path(self._node)]} if self._node else {}
        self._identity=self._call({'action':'identity'})
    @property
    def identity(self):
        # Conservative exact recheck. Not a metadata/mtime shortcut.
        actual=self._call({'action':'identity'})
        require(actual==self._identity,'CORE_IDENTITY_CHANGED')
        return dict(self._identity)
    def _call(self,value):
        if not self._manifest.is_file() or not self._node:raise SharedChangeError('CORE_UNAVAILABLE')
        try:now={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in self._runtime}
        except OSError:raise SharedChangeError('CORE_UNAVAILABLE') from None
        require(now==self._runtime,'CORE_RUNTIME_CHANGED')
        raw=canonical(value);require(len(raw)<=8*1024*1024,'RESOURCE_LIMIT')
        try:
            cp=subprocess.run([self._node,'--max-old-space-size=128',str(WORKER),str(self._manifest)],input=raw,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=self._timeout,env=clean_env(),cwd=WORKER.parent)
        except subprocess.TimeoutExpired:raise SharedChangeError('CORE_TIMEOUT') from None
        except OSError:raise SharedChangeError('CORE_UNAVAILABLE') from None
        require(len(cp.stdout)<=4*1024*1024,'CORE_OUTPUT_LIMIT')
        try:result=json.loads(cp.stdout)
        except (ValueError,UnicodeError):raise SharedChangeError('CORE_OUTPUT_INVALID') from None
        require(type(result) is dict,'CORE_OUTPUT_INVALID')
        if cp.returncode!=0 or result.get('ok') is not True:
            code=result.get('code','CORE_EXECUTION_FAILED');raise SharedChangeError(code if type(code) is str else 'CORE_OUTPUT_INVALID')
        require(set(result)=={'ok','value'},'CORE_OUTPUT_INVALID');return result['value']
    def validate(self,request):
        result=self._call({'action':'validate','request':request})
        require(result.get('engine')==self._identity,'CORE_IDENTITY_CHANGED');return result
    def make(self,**input):return self._call({'action':'make','input':input})
