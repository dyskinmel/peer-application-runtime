"""Standalone owned child; SIGKILL only itself at a named fault boundary."""
import os,sys,signal
from pathlib import Path
R=Path(__file__).resolve().parents[3]
sys.dont_write_bytecode=True
for p in [R,Path(__file__).parent,R/'tests/product/auth-store',R/'tests/product/space-auth']+[x for x in (R/'experiments').iterdir() if x.is_dir()]:sys.path.insert(0,str(p))
from apply_support import ApplyTest
f=ApplyTest();f.setUp()
try:
 f.close();f.root=Path(sys.argv[1]);f.db=f.Store.open(f.root,provider=f.p,allow_unpatched_sqlite=True);f.db.reactivate(f.s.space,f.s.devices[0]['secret']);f.a=f.make()
 stage=sys.argv[2]
 def kill(s):
  if s==stage:
   print('KILL_BOUNDARY:'+s,flush=True);os.kill(os.getpid(),signal.SIGKILL)
 f.a.observer=kill
 f.call([bytes.fromhex(sys.argv[3])])
 raise RuntimeError('requested boundary not reached')
finally:f.doCleanups()
