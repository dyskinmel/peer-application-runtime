import asyncio,json,os,signal,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secure_support import API
from process_fixture import Peer,h
from product.wp04.exchange import Source
WORKER=Path(__file__).with_name('secure_worker.py')

class ProcessTLSTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.load();self.raw=[];self.streams=[];self.children=[]
        self.tmp=tempfile.TemporaryDirectory(prefix='par-process-tls-');self.root=Path(self.tmp.name)
        self.reader=Peer(self.root/'reader');d=self.reader.s.devices[1]
        self.reader.source=Source(self.reader.box,d['cert'],d['seed'])
    async def asyncTearDown(self):
        await self.cleanup()
        for child in self.children:
            if child.returncode is None:child.terminate()
            await child.communicate()
        self.reader.close();self.tmp.cleanup()
    async def spawn(self,count=1,mode='normal'):
        pairs=[socket.socketpair() for _ in range(count)];self.raw.extend(s for pair in pairs for s in pair)
        fds=[b.fileno() for a,b in pairs]
        p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(WORKER),json.dumps(fds),str(self.root/'provider'),str(self.pki.path),mode,
            pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        self.children.append(p)
        for a,b in pairs:b.close()
        return p,[a for a,b in pairs]
    async def session(self,sock,limits=None):
        stream=await self.m.TLSStream.open(sock,self.pki.config(self.m,False),limits=limits)
        self.streams.append(stream)
        binding=self.m.PeerBinding('provider',self.reader.s.devices[0]['cert'],tuple(self.reader.source.scope),self.pki.pin('server'),9)
        return self.m.ReadSession(stream,self.reader.source,binding,lambda:9)
    async def test_real_process_have_need_get(self):
        p,socks=await self.spawn(3)
        before=self.reader.db._storage.connection.total_changes
        c=await self.session(socks[0]);have=await c.request('have',{0:None,1:0,2:16});self.assertEqual(len(have[2]),2)
        c=await self.session(socks[1]);need=await c.request('need',[h('inner:a')]);d=need[1][0][1]
        c=await self.session(socks[2]);got=await c.request('get',{0:need[0],1:d[0],2:d[1]})
        self.assertEqual(got[3],self.reader.chain()[0][0])
        self.assertEqual(got[5],'ENCRYPTED_PENDING_BYTES')
        out,err=await asyncio.wait_for(p.communicate(),3);self.assertEqual(p.returncode,0,err.decode())
        result=json.loads(out);self.assertTrue(result['db_unchanged'] and result['closed'])
        self.assertEqual(result['process_group'],os.getpgrp())
        self.assertEqual(before,self.reader.db._storage.connection.total_changes)
        self.assertEqual(self.reader.box.usage()['records'],0)
        self.assertTrue(all(x['version']=='TLSv1.3' and x['client_pin_verified'] for x in result['exchanges']))
    async def test_kill_before_response_not_absence(self):
        p,socks=await self.spawn(mode='kill-before-response');c=await self.session(socks[0])
        with self.assertRaises(self.m.TransportError):await c.request('need',[h('inner:a')])
        await p.communicate();self.assertEqual(p.returncode,-signal.SIGKILL)
    async def test_kill_after_handshake_not_success(self):
        p,socks=await self.spawn(mode='kill-after-handshake')
        try:
            c=await self.session(socks[0])
        except self.m.TransportError:pass
        else:
            with self.assertRaises(self.m.TransportError):await c.request('need',[h('inner:a')])
        await p.communicate();self.assertEqual(p.returncode,-signal.SIGKILL)
    async def test_stalled_child_has_finite_handshake_deadline(self):
        p,socks=await self.spawn(mode='stall')
        with self.assertRaises(self.m.TransportError):await self.session(socks[0],self.m.Limits(timeout=.1))
        self.assertEqual(socks[0].fileno(),-1)
    async def test_no_dns_or_ip_dial_in_local_tls(self):
        p,socks=await self.spawn()
        with patch('socket.getaddrinfo',side_effect=AssertionError('unexpected DNS')),patch.object(socket.socket,'connect',side_effect=AssertionError('unexpected IP dial')):
            c=await self.session(socks[0]);value=await c.request('need',[h('inner:a')]);self.assertIsNotNone(value[1][0][1])
        out,err=await p.communicate();self.assertEqual(p.returncode,0,err.decode())
    async def test_current_process_group_preserved(self):
        p,socks=await self.spawn();self.assertEqual(os.getpgid(p.pid),os.getpgrp())
        c=await self.session(socks[0]);await c.request('have',{0:None,1:0,2:16})
        out,err=await p.communicate();self.assertEqual(p.returncode,0,err.decode())
