"""Node -> Python owner, real files/SQLite; recovery has no materializer."""
import asyncio,dataclasses,json,os,signal,socket,sys,unittest
from pathlib import Path
import test_intent_coordinator as fixtures
from product.wp09.par_application_intent import LocalPinStore,AnchoredApplication
W=Path(__file__).with_name('owner_worker.py');N=W.with_name('node_actor.mjs')
class ApplicationProcessTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.f=f=fixtures.IntentCoordinatorTests();f.setUp();self.addCleanup(f.doCleanups);self.children=[]
  store=LocalPinStore.create(f.root.parent/'anchor',AnchoredApplication.binding(f.c),f.j.pin());store.close()
  config={'database':str(f.root),'plan':f.plan.to_bytes().hex(),'target':f.target.hex(),'pin':dataclasses.asdict(f.j.pin())}
  self.path=f.root.parent/'config.json';self.path.write_text(json.dumps(config));self.path.chmod(0o600)
  self.caller=f.root.parent/'caller';self.caller.mkdir(mode=0o700)
  f.j.close();f.box.close();f.close()
 async def asyncTearDown(self):
  for p in self.children:
   if p.returncode is None:p.kill()
   await p.communicate()
 async def child(self,args,fds):
  p=await asyncio.create_subprocess_exec(*map(str,args),pass_fds=fds,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,stdin=asyncio.subprocess.DEVNULL);self.children.append(p);return p
 async def phase(self,mode):
  a,b=socket.socketpair()
  try:
   owner=await self.child([sys.executable,'-I','-S','-B',W,self.path,mode,a.fileno()],(a.fileno(),))
   line=await asyncio.wait_for(owner.stdout.readline(),15)
   if not line:
    _,err=await owner.communicate();self.fail(err.decode())
   ready=json.loads(line);self.assertEqual(ready['pgid'],os.getpgrp())
   node=await self.child(['node',N,b.fileno(),json.dumps(ready['context']),json.dumps(ready['targets']),self.caller,mode],(b.fileno(),))
  finally:a.close();b.close()
  out,err=await asyncio.wait_for(node.communicate(),25);self.assertEqual(node.returncode,0,err.decode());nr=json.loads(out)
  out,err=await asyncio.wait_for(owner.communicate(),15)
  if mode.startswith('kill-'):self.assertEqual(owner.returncode,-signal.SIGKILL);orr=None
  else:
   self.assertEqual(owner.returncode,0,err.decode());orr=json.loads(out);self.assertTrue(orr['cleanup']);self.assertEqual(orr['pgid'],os.getpgrp());self.assertFalse(orr['real_core_executed'])
  self.assertEqual(nr['channel']['inflight'],0);return nr,orr
 async def test_synthetic_complete_one_event_one_nonce(self):
  n,o=await self.phase('complete');self.assertEqual(o['counts']['document_apply_events'],1);self.assertEqual(o['counts']['document_apply_nonces'],1);self.assertTrue(n['stored']['dispatchAttempted']);self.assertEqual(o['state'],'RETIRED')
 async def test_prepare_loss_reopen_original_only(self):
  n,_=await self.phase('kill-prepare');self.assertFalse(n['stored']['dispatchAttempted']);self.assertEqual(n['stored']['original']['operationId'],'6f'*16)
  n,o=await self.phase('recover');self.assertEqual(o['state'],'PREPARED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_dispatch_loss_reopen_absence_does_not_replay(self):
  n,_=await self.phase('kill-dispatch');self.assertTrue(n['stored']['dispatchAttempted'])
  n,o=await self.phase('recover');self.assertEqual(o['state'],'DISPATCHED');self.assertEqual(n['state']['snapshot']['journal']['operationState'],'NOT_OBSERVED');self.assertTrue(n['state']['dispatchAttempted']);self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_commit_loss_reopen_inquiry_no_core(self):
  await self.phase('kill-commit');n,o=await self.phase('recover');self.assertEqual(o['state'],'OBSERVED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_events'],1);self.assertEqual(o['counts']['document_apply_nonces'],1)
 async def test_retire_loss_reopen_retired(self):
  await self.phase('kill-retire');n,o=await self.phase('recover');self.assertEqual(o['state'],'RETIRED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_events'],1)
 async def test_core_blocked_before_dispatch(self):
  n,o=await self.phase('blocked');self.assertEqual(o['state'],'PREPARED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_readonly_no_caller_original(self):
  n,o=await self.phase('readonly');self.assertIsNone(n['stored']);self.assertEqual(o['state'],'EMPTY');self.assertEqual(o['core_calls'],0)
