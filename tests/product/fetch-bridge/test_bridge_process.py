"""Three-level encrypted dependencies; actual private TLS/OS processes/Inbox."""
import asyncio,json,os,signal,socket,sys,tempfile,unittest
from pathlib import Path
from secure_support import TestPKI
WORKER=Path(__file__).with_name('bridge_worker.py')
class BridgeProcessTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):cls.pki=TestPKI()
    @classmethod
    def tearDownClass(cls):cls.pki.close()
    async def asyncSetUp(self):
        self.assertTrue(WORKER.is_file(),'three-level fetch bridge worker missing')
        self.temp=tempfile.TemporaryDirectory(prefix='par-bridge-process-');self.root=Path(self.temp.name);self.children=[]
    async def asyncTearDown(self):
        for p in self.children:
            if p.returncode is None:p.terminate()
            await p.communicate()
        self.temp.cleanup()
    async def child(self,argv,fds=()):
        p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(WORKER),*map(str,argv),pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        self.children.append(p);return p
    async def run_phase(self,mode,count,proof=None,expected=0):
        pairs=[socket.socketpair()for _ in range(count)]
        try:
            a=[p[0].fileno()for p in pairs];b=[p[1].fileno()for p in pairs]
            server=await self.child(['provider',json.dumps(b),self.root/'provider',self.pki.path,'serve','{}'],b)if count else None
            receiver=await self.child(['receiver',json.dumps(a),self.root/'receiver',self.pki.path,mode,json.dumps(proof or{})],a)
        finally:
            for a,b in pairs:a.close();b.close()
        out,err=await asyncio.wait_for(receiver.communicate(),15)
        self.assertEqual(receiver.returncode,expected,err.decode())
        rows=[json.loads(line)for line in out.splitlines()]
        remote=None
        if server:
            if expected!=0 and server.returncode is None:server.terminate()
            so,se=await asyncio.wait_for(server.communicate(),8)
            if expected==0:
                self.assertEqual(server.returncode,0,se.decode());remote=json.loads(so)
        return rows[-1],remote,rows[0].get('proof')
    async def test_three_level_reverse_rounds_and_explicit_core_block(self):
        seed,_,_=await self.run_phase('seed',2);self.assertEqual(seed['inbox_records'],1)
        one,s,_=await self.run_phase('round',3,seed['proof']);self.assertEqual(one['inbox_records'],2);self.assertEqual([x['method']for x in s['requests']],['need','have','get'])
        two,s,_=await self.run_phase('round',3,one['proof']);self.assertEqual(two['inbox_records'],3)
        offline,_,_=await self.run_phase('validate',0,two['proof']);self.assertEqual(offline['network_calls'],0);self.assertEqual(offline['observation']['records'][0]['validation']['reason'],'CORE_UNAVAILABLE')
        self.assertTrue(offline['db_unchanged']);self.assertFalse(offline['observation']['applied']);self.assertEqual(offline['process_group'],os.getpgrp())
    async def crash(self,stage,expected_records):
        seed,_,_=await self.run_phase('seed',2)
        _,_,proof=await self.run_phase('kill:'+stage,3,seed['proof'],-signal.SIGKILL)
        offline,_,_=await self.run_phase('inspect',0,proof);self.assertEqual(offline['inbox_records'],expected_records);self.assertEqual(offline['network_calls'],0)
        resumed,s,_=await self.run_phase('round',3,offline['proof']);self.assertEqual(resumed['inbox_records'],expected_records+1)
        self.assertEqual([x['method']for x in s['requests']],['need','have','get']);self.assertTrue(resumed['db_unchanged'])
        self.assertFalse(resumed['observation']['applied']or resumed['observation']['acknowledged'])
        if expected_records==2:self.assertEqual(s['requests'][-1]['innerId'],resumed['inner_a'])
    async def test_kill_before_publish_retries_only_explicit_missing_round(self):await self.crash('inbox.before_publish',1)
    async def test_kill_after_publish_does_not_refetch_saved_parent(self):await self.crash('inbox.after_publish',2)
    async def test_kill_after_directory_sync_preserves_parent(self):await self.crash('inbox.after_dirsync',2)
    async def test_kill_before_receipt_preserves_parent(self):await self.crash('inbox.before_receipt',2)
    async def test_changed_external_pin_blocks_offline_reopen(self):
        seed,_,_=await self.run_phase('seed',2);proof=dict(seed['proof']);proof['planSha']='0'*64
        p=await self.child(['receiver','[]',self.root/'receiver',self.pki.path,'inspect',json.dumps(proof)])
        out,err=await asyncio.wait_for(p.communicate(),10);self.assertNotEqual(p.returncode,0);self.assertIn(b'METADATA_PIN',err)
