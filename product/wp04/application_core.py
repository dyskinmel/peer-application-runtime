"""Byte-pinned materialization candidate; actual artifact execution is separate."""
import hashlib,json,subprocess
from pathlib import Path
from harness.common import clean_env
from .core_port import NodeCorePort
from .contracts import canonical,require,SharedChangeError

class NodeMaterializationPort(NodeCorePort):
 def __init__(self,manifest,*,timeout=30):
  super().__init__(manifest,timeout=timeout)
  self._apply_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(__file__).with_name('materializer.mjs'),Path(__file__).with_name('materializer_worker.mjs'))}
 @property
 def identity(self):
  try:require({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in self._apply_files}==self._apply_files,'CORE_RUNTIME_CHANGED')
  except OSError:raise SharedChangeError('CORE_UNAVAILABLE') from None
  return super().identity
 def materialize(self,request):
  before=self.identity;data=canonical({'action':'materialize','request':request});require(len(data)<=8*1024*1024,'RESOURCE_LIMIT')
  try:
   cp=subprocess.run([self._node,'--max-old-space-size=128',str(Path(__file__).with_name('materializer_worker.mjs')),str(self._manifest)],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=self._timeout,env=clean_env(),cwd=Path(__file__).parent)
  except subprocess.TimeoutExpired:raise SharedChangeError('CORE_TIMEOUT') from None
  except OSError:raise SharedChangeError('CORE_UNAVAILABLE') from None
  require(len(cp.stdout)<=4*1024*1024,'CORE_OUTPUT_LIMIT')
  try:r=json.loads(cp.stdout)
  except (ValueError,UnicodeError):raise SharedChangeError('CORE_OUTPUT_INVALID') from None
  require(type(r) is dict,'CORE_OUTPUT_INVALID')
  if cp.returncode or r.get('ok') is not True:
   code=r.get('code','CORE_EXECUTION_FAILED');raise SharedChangeError(code if type(code) is str else 'CORE_OUTPUT_INVALID')
  require(set(r)=={'ok','value'} and before==self.identity,'CORE_IDENTITY_CHANGED');return r['value']
