"""Explicit SYNTHETIC materializer; real anchor, SQLite and private socket."""
from pathlib import Path
import sys,os,json,signal,asyncio,socket
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools import check_application_intent
from anchored_process_support import open_anchored_runtime
from product.wp09.par_application_owner import ApplicationOwner,serve_application_connected
async def main():
 config=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2];fd=int(sys.argv[3]);f=open_anchored_runtime(config);owner=None
 try:
  if mode=='recover':f.app._core=None
  elif mode!='blocked':f.port.identity['kind']='automerge' # Test double identity only.
  def kill():os.kill(os.getpid(),signal.SIGKILL)
  def journal(stage):
   if stage=='journal.before_return' and (f.j.pin().sequence,mode)in((1,'kill-prepare'),(2,'kill-dispatch'),(4,'kill-retire')):kill()
  def applying(stage):
   if mode=='kill-commit'and stage=='apply.after_commit':kill()
  f.j.observer=journal;f.app.observer=applying
  owner=ApplicationOwner(f.d,local_experiment=True)
  ch=owner.attach();ctx=owner.context(ch);owner.detach(ch)
  print(json.dumps({'ready':True,'context':ctx,'targets':[f.target.hex()],'pgid':os.getpgrp()}),flush=True)
  await serve_application_connected(owner,socket.socket(fileno=fd),allow_apply=mode!='readonly',read_timeout=20)
  stats=await owner.close()
  print(json.dumps({'counts':f.nums(),'core_calls':f.port.calls,'state':f.j.status()['state'],'cleanup':stats['cleanupComplete'],'real_core_executed':False,'pgid':os.getpgrp()}),flush=True)
 finally:
  if owner:await owner.close()
  f.doCleanups()
asyncio.run(main())
