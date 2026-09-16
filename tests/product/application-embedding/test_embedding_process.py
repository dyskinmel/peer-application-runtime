"""Actual Node reference view logic -> private owner; DOM is a contract double.
Positive materializer is explicitly synthetic; persistence/SQLite are real.
"""
import asyncio,json,os,signal,socket,sys,unittest
from pathlib import Path
from test_application_process import ApplicationProcessTests
N=Path(__file__).with_name('node_actor.mjs')
W=Path(__file__).parents[1]/'application-owner/owner_worker.py'
class EmbeddingProcessTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.f=ApplicationProcessTests();await self.f.asyncSetUp();self.addCleanup(self.f.doCleanups)
 async def asyncTearDown(self):await self.f.asyncTearDown()
 async def phase(self,mode):
  a,b=socket.socketpair()
  try:
   owner=await self.f.child([sys.executable,'-I','-S','-B',W,self.f.path,mode,a.fileno()],(a.fileno(),))
   line=await asyncio.wait_for(owner.stdout.readline(),15)
   if not line:
    _,err=await owner.communicate();self.fail(err.decode())
   ready=json.loads(line);self.assertEqual(ready['pgid'],os.getpgrp())
   node=await self.f.child(['node',N,b.fileno(),json.dumps(ready['context']),json.dumps(ready['targets']),self.f.caller,mode],(b.fileno(),))
  finally:a.close();b.close()
  out,err=await asyncio.wait_for(node.communicate(),30);self.assertEqual(node.returncode,0,err.decode());n=json.loads(out)
  out,err=await asyncio.wait_for(owner.communicate(),15)
  if mode.startswith('kill-'):self.assertEqual(owner.returncode,-signal.SIGKILL);o=None
  else:
   self.assertEqual(owner.returncode,0,err.decode());o=json.loads(out);self.assertTrue(o['cleanup']);self.assertEqual(o['pgid'],os.getpgrp());self.assertFalse(o['real_core_executed'])
  self.assertEqual(n['cleanup'],'DETACHED');self.assertEqual(n['channel']['inflight'],0)
  return n,o
 async def test_view_complete_retains_original_one_nonce(self):
  n,o=await self.phase('complete');self.assertEqual(o['state'],'RETIRED');self.assertEqual(o['counts']['document_apply_events'],1);self.assertEqual(o['counts']['document_apply_nonces'],1);self.assertTrue(n['stored']['dispatchAttempted'])
 async def test_view_stage_detach_without_request(self):
  n,o=await self.phase('stage-only');self.assertEqual(n['calls'],[]);self.assertIsNotNone(n['stored']);self.assertEqual(o['state'],'EMPTY');self.assertEqual(o['core_calls'],0)
 async def test_view_marker_then_detach_before_send(self):
  n,o=await self.phase('marker-only');self.assertNotIn('dispatch',n['calls']);self.assertTrue(n['stored']['dispatchAttempted']);self.assertEqual(o['state'],'PREPARED');self.assertEqual(o['counts']['document_apply_nonces'],0)
  n,o=await self.phase('recover');self.assertEqual(n['calls'],['observe','inquire']);self.assertTrue(n['state']['dispatchAttempted']);self.assertEqual(o['core_calls'],0)
 async def test_view_prepare_loss_reopen_original(self):
  await self.phase('kill-prepare');n,o=await self.phase('recover');self.assertEqual(o['state'],'PREPARED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_view_dispatch_loss_no_replay(self):
  await self.phase('kill-dispatch');n,o=await self.phase('recover');self.assertEqual(o['state'],'DISPATCHED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_view_commit_loss_recovers_without_materializer(self):
  await self.phase('kill-commit');n,o=await self.phase('recover');self.assertEqual(o['state'],'OBSERVED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_events'],1);self.assertEqual(o['counts']['document_apply_nonces'],1)
 async def test_view_retire_loss_no_second_dispatch(self):
  await self.phase('kill-retire');n,o=await self.phase('recover');self.assertEqual(o['state'],'RETIRED');self.assertEqual(o['core_calls'],0);self.assertEqual(o['counts']['document_apply_events'],1)
 async def test_view_core_blocked_keeps_caller_marker(self):
  n,o=await self.phase('blocked');self.assertEqual(n['state']['snapshot']['journal']['operationState'],'CORE_BLOCKED');self.assertTrue(n['stored']['dispatchAttempted']);self.assertEqual(o['counts']['document_apply_nonces'],0)
 async def test_view_readonly_does_not_create_original(self):
  n,o=await self.phase('readonly');self.assertIsNone(n['stored']);self.assertEqual(o['core_calls'],0);self.assertEqual(o['state'],'EMPTY')
