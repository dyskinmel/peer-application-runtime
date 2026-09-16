"""Separate receiver/provider; actual private mTLS, SQLite, fsynced Inbox."""
import asyncio,json,os,signal,socket,sys,tempfile,unittest
from pathlib import Path
from secure_support import TestPKI
ROOT=Path(__file__).resolve().parents[3]
SERVER=ROOT/'tests/product/secure-transport/secure_worker.py'
WORKER=Path(__file__).with_name('fetch_worker.py')

class ProcessFetchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):cls.pki=TestPKI()
    @classmethod
    def tearDownClass(cls):cls.pki.close()
    async def asyncSetUp(self):
        self.assertTrue(WORKER.is_file(),'secure fetch process worker missing')
        self.temp=tempfile.TemporaryDirectory(prefix='par-fetch-process-');self.root=Path(self.temp.name);self.children=[]
    async def asyncTearDown(self):
        for p in self.children:
            if p.returncode is None:p.terminate()
            await p.communicate()
        self.temp.cleanup()
    async def child(self,argv,pass_fds=()):
        p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',*map(str,argv),pass_fds=pass_fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        self.children.append(p);return p
    async def transfer(self,mode,count,plan_sha='',cp_sha=''):
        pairs=[socket.socketpair()for _ in range(count)]
        try:
            sfds=[b.fileno()for a,b in pairs];rfds=[a.fileno()for a,b in pairs]
            server=await self.child([SERVER,json.dumps(sfds),self.root/'provider',self.pki.path,'normal'],sfds)if count else None
            reader=await self.child([WORKER,json.dumps(rfds),self.root/'receiver',self.pki.path,mode,plan_sha,cp_sha],rfds)
        finally:
            for a,b in pairs:a.close();b.close()
        return server,reader
    async def finish(self,p,expect=0):
        out,err=await asyncio.wait_for(p.communicate(),12);self.assertEqual(p.returncode,expect,err.decode());return [json.loads(line)for line in out.splitlines()]
    async def test_actual_two_process_fetch_save_reopen(self):
        server,reader=await self.transfer('fresh',3);rows=await self.finish(reader);remote=(await self.finish(server))[0]
        self.assertEqual(rows[-1]['progress']['stored'],2);self.assertFalse(rows[-1]['progress']['applied']);self.assertTrue(rows[-1]['db_unchanged']);self.assertTrue(remote['db_unchanged']);self.assertEqual(len(remote['exchanges']),3)
        _,reader=await self.transfer('resume',0,rows[0]['planSha'],rows[0]['checkpointSha']);r=(await self.finish(reader))[-1]
        self.assertEqual(r['progress']['stored'],2);self.assertEqual(r['network_calls'],0);self.assertEqual(r['process_group'],os.getpgrp())
    async def crash_resume(self,stage,expected):
        server,reader=await self.transfer('kill:'+stage,3);rows=await self.finish(reader,-signal.SIGKILL)
        if server.returncode is None:server.terminate()
        await server.communicate()
        proof=rows[0];_,reader=await self.transfer('resume',0,proof['planSha'],proof['checkpointSha']);r=(await self.finish(reader))[-1]
        self.assertEqual(r['progress']['stored'],expected);self.assertEqual(r['network_calls'],0)
        server,reader=await self.transfer('replan-continue',3-expected,proof['planSha'],proof['checkpointSha']);r=(await self.finish(reader))[-1];s=(await self.finish(server))[0]
        self.assertEqual(r['progress']['stored'],2);self.assertEqual(r['network_calls'],3-expected);self.assertEqual(len(s['exchanges']),3-expected);self.assertEqual([x['result']['method']for x in s['exchanges']],['have']+['get']*(2-expected))
        self.assertTrue(r['db_unchanged']);self.assertEqual(r['inbox_records'],2);self.assertFalse(r['progress']['applied']or r['progress']['acknowledged'])
    async def test_kill_before_publish_not_stored(self):await self.crash_resume('inbox.before_publish',0)
    async def test_kill_after_publish_reconcile_without_refetch(self):await self.crash_resume('inbox.after_publish',1)
    async def test_kill_after_dirsync_reconcile_without_refetch(self):await self.crash_resume('inbox.after_dirsync',1)
    async def test_kill_before_receipt_reconcile_without_refetch(self):await self.crash_resume('inbox.before_receipt',1)
    async def test_wrong_external_plan_digest_blocks_resume(self):
        s,r=await self.transfer('fresh',3);rows=await self.finish(r);await self.finish(s)
        _,r=await self.transfer('resume',0,'0'*64,rows[0]['checkpointSha']);out,err=await asyncio.wait_for(r.communicate(),8)
        self.assertNotEqual(r.returncode,0);self.assertIn(b'METADATA_PIN',err)
    async def test_new_inbox_same_scope_does_not_reuse_plan(self):
        s,r=await self.transfer('fresh',3);rows=await self.finish(r);await self.finish(s)
        inbox=self.root/'receiver/peer/inbox';inbox.rename(inbox.parent/'old-inbox')
        _,r=await self.transfer('resume',0,rows[0]['planSha'],rows[0]['checkpointSha']);out,err=await asyncio.wait_for(r.communicate(),8)
        self.assertNotEqual(r.returncode,0);self.assertIn(b'INBOX_GENERATION',err)
    async def test_demo_is_executable(self):
        p=await self.child([ROOT/'examples/secure_fetch_demo.py']);out,err=await asyncio.wait_for(p.communicate(),12);self.assertEqual(p.returncode,0,err.decode());rows=[json.loads(out)]
        self.assertEqual(rows[-1]['result'],'PASS');self.assertEqual(rows[-1]['stored'],2);self.assertFalse(rows[-1]['applied']);self.assertEqual(rows[-1]['resume_network_calls'],0)
    async def test_provider_restart_requires_explicit_new_snapshot(self):
        s,r=await self.transfer('kill:inbox.before_receipt',3);rows=await self.finish(r,-signal.SIGKILL)
        if s.returncode is None:s.terminate()
        await s.communicate();proof=rows[0]
        s,r=await self.transfer('continue',1,proof['planSha'],proof['checkpointSha'])
        out,err=await asyncio.wait_for(r.communicate(),12);so,se=await asyncio.wait_for(s.communicate(),12)
        self.assertNotEqual(r.returncode,0);self.assertNotEqual(s.returncode,0);self.assertIn(b'STALE_VIEW',se)
