"""Node -> owner -> provider, actual private descriptors, TLS and Inbox."""
import asyncio,json,os,signal,socket,sys,tempfile,unittest
from pathlib import Path
from secure_support import TestPKI
ROOT=Path(__file__).resolve().parents[3];WORKER=Path(__file__).with_name('owner_worker.py');NODE=Path(__file__).with_name('node_actor.mjs')
class OwnerProcessTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):cls.pki=TestPKI()
    @classmethod
    def tearDownClass(cls):cls.pki.close()
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='par-owner-three-');self.root=Path(self.temp.name);self.children=[]
    async def asyncTearDown(self):
        for p in self.children:
            if p.returncode is None:p.terminate()
            await p.communicate()
        self.temp.cleanup()
    async def child(self,argv,fds):
        p=await asyncio.create_subprocess_exec(*map(str,argv),pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        self.children.append(p);return p
    async def phase(self,mode,n,digest=''):
        pipes=[socket.socketpair()for _ in range(n)];ui=socket.socketpair()
        try:
            local=[a.fileno()for a,b in pipes];remote=[b.fileno()for a,b in pipes]
            provider=await self.child([sys.executable,'-I','-S','-B',WORKER,'stall'if mode in('cancel','deadline')else'provider',json.dumps(remote),self.root/'provider',self.pki.path,mode,-1],tuple(remote))if n else None
            owner=await self.child([sys.executable,'-I','-S','-B',WORKER,'owner',json.dumps(local),self.root/'owner',self.pki.path,mode,ui[0].fileno()],tuple(local+[ui[0].fileno()]))
            line=await asyncio.wait_for(owner.stdout.readline(),5)
            if not line:
                _,error=await owner.communicate();self.fail(error.decode())
            ready=json.loads(line);self.assertTrue(ready['ready'])
            node=await self.child(['node',NODE,ui[1].fileno(),json.dumps(ready['pin']),mode,digest],(ui[1].fileno(),))
        finally:
            for pair in pipes+[ui]:
                for sock in pair:sock.close()
        out,err=await asyncio.wait_for(node.communicate(),15);self.assertEqual(node.returncode,0,err.decode());nr=json.loads(out)
        oo,oe=await asyncio.wait_for(owner.communicate(),8)
        if mode.startswith('kill-'):
            self.assertEqual(owner.returncode,-signal.SIGKILL);own=None
        else:
            self.assertEqual(owner.returncode,0,oe.decode());own=json.loads(oo)
            self.assertEqual(own['owner']['inflight'],0);self.assertTrue(own['owner']['cleanupComplete']);self.assertTrue(own['db_unchanged']);self.assertEqual(own['process_group'],os.getpgrp())
        pr=None
        if provider:
            po,pe=await asyncio.wait_for(provider.communicate(),8)
            self.assertEqual(provider.returncode,0,pe.decode());pr=json.loads(po)
        return nr,own,pr
    async def test_two_rounds_three_level_and_core_blocked(self):
        n,o,p=await self.phase('rounds',6);self.assertEqual(o['candidate_count'],3);self.assertEqual(p['requests'],['need','have','get']*2);self.assertEqual(n['state']['snapshot']['observation']['records'][0]['validation']['reason'],'CORE_UNAVAILABLE')
    async def test_save_response_loss_offline_resume_then_missing_only(self):
        n,_,p=await self.phase('kill-fetch',3);self.assertTrue(n['state']['resumeRequired']);self.assertEqual(len(n['planDigest']),64)
        resumed,o,_=await self.phase('resume',0,n['planDigest']);self.assertEqual(o['candidate_count'],2);self.assertEqual(o['network_calls'],0)
        final,o,p=await self.phase('round',3);self.assertEqual(o['candidate_count'],3);self.assertEqual(p['requests'],['need','have','get'])
    async def test_accept_response_loss_keeps_external_plan_sha(self):
        n,_,p=await self.phase('kill-accept',2);self.assertTrue(n['state']['resumeRequired']);self.assertEqual(len(n['planDigest']),64);self.assertEqual(p['requests'],['need','have'])
        # The plan exists, but it must not be blindly executed against a restarted provider snapshot.
        from product.wp09.par_secure_fetch import FetchPlan
        plan=FetchPlan.load(self.root/'owner/plans'/(n['planDigest']+'.cbor'),expected_sha256=n['planDigest']);self.assertEqual(plan.digest,n['planDigest'])
    async def test_readonly_owner_rejects_raw_propose(self):
        n,o,_=await self.phase('readonly',0);self.assertEqual(o['candidate_count'],1);self.assertEqual(o['network_calls'],0)
    async def test_cancel_stalled_tls_reaps_worker(self):
        n,o,p=await self.phase('cancel',1);self.assertEqual(n['stopped'],'CANCELLED');self.assertEqual(o['candidate_count'],1)
    async def test_deadline_stalled_tls_reaps_worker(self):
        n,o,p=await self.phase('deadline',1);self.assertIsNotNone(n['stopped']);self.assertEqual(o['candidate_count'],1)
