"""Real connected AF_UNIX sockets, finite frame queues; owner supplies capability."""
import asyncio, importlib, json, socket, struct
from test_host import HostSupport

class TransportTests(HostSupport):
    async def connected(self,h):
        try:m=importlib.import_module('product.wp10.transport')
        except ModuleNotFoundError:m=None
        self.assertIsNotNone(m,'connected event host transport not implemented')
        a,b=socket.socketpair();b.setblocking(False)
        task=asyncio.create_task(m.serve_connected(h,a,b'c'*16,read_timeout=.5,write_timeout=.5))
        return b,task
    async def send(self,s,value):
        raw=json.dumps(value,separators=(',',':')).encode();await asyncio.get_running_loop().sock_sendall(s,struct.pack('!I',len(raw))+raw)
    async def recv(self,s):
        loop=asyncio.get_running_loop()
        async def exactly(n):
            out=b''
            while len(out)<n:
                b=await loop.sock_recv(s,n-len(out))
                if not b:raise EOFError()
                out+=b
            return out
        n=struct.unpack('!I',await exactly(4))[0];self.assertLessEqual(n,1500000)
        return json.loads(await exactly(n))
    async def open_remote(self,h):
        s,t=await self.connected(h);hello=await self.recv(s)
        await self.send(s,{'v':1,'id':'1','op':'open','args':{'context':hello['context'],'expectedCursor':None}})
        r=await self.recv(s);return s,t,hello,r['value']['result']['sessionId']
    def test_connected_descriptor_real_poll(self):
        async def body(h):
            self.emit();s,t,hello,session=await self.open_remote(h)
            await self.send(s,{'v':1,'id':'2','op':'poll','args':{'sessionId':session,'limit':1,'byteLimit':1024}})
            r=await self.recv(s);self.assertEqual(r['value']['result']['events'][0]['payload']['count']['value'],str(2**63+1))
            s.close();await asyncio.wait_for(t,1);self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_abort_wait_allows_cleanup(self):
        async def body(h):
            s,t,_,session=await self.open_remote(h)
            await self.send(s,{'v':1,'id':'2','op':'poll','args':{'sessionId':session,'limit':1,'byteLimit':1024}});r=await self.recv(s)
            await self.send(s,{'v':1,'id':'3','op':'wait','args':{'sessionId':session,'ticket':r['value']['ticket']}})
            await asyncio.sleep(.01);self.assertEqual(h.stats()['waiters'],1)
            await self.send(s,{'v':1,'cancel':'3'});r=await self.recv(s);self.assertEqual(r['error'],'HOST_REQUEST_CANCELLED')
            await self.send(s,{'v':1,'id':'4','op':'cancel','args':{'sessionId':session}});self.assertIn('value',await self.recv(s))
            s.close();await t;self.assertEqual(self.journal.inspect()['events'],0)
        self.run_async(body)
    def test_oversized_length_closes_connection_no_effect(self):
        async def body(h):
            s,t=await self.connected(h);await self.recv(s)
            await asyncio.get_running_loop().sock_sendall(s,struct.pack('!I',65537))
            await asyncio.wait_for(t,1);self.assertEqual(h.stats()['channels'],0);s.close()
            self.assertEqual(self.journal.inspect()['consumers'],0)
        self.run_async(body)
    def test_duplicate_json_key_rejected(self):
        async def body(h):
            s,t=await self.connected(h);await self.recv(s)
            raw=b'{"v":1,"id":"1","id":"2","op":"open","args":{}}'
            await asyncio.get_running_loop().sock_sendall(s,struct.pack('!I',len(raw))+raw)
            await asyncio.wait_for(t,1);s.close();self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_reused_request_id_closes_without_replay(self):
        async def body(h):
            s,t,_,session=await self.open_remote(h)
            await self.send(s,{'v':1,'id':'1','op':'cursor','args':{'sessionId':session}})
            await asyncio.wait_for(t,1);s.close();self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_frame_truncation_cleanup(self):
        async def body(h):
            s,t=await self.connected(h);await self.recv(s)
            await asyncio.get_running_loop().sock_sendall(s,b'\0\0\0\x20{}');s.close();await t
            self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_eof_does_not_ack(self):
        async def body(h):
            self.emit();s,t,_,session=await self.open_remote(h)
            await self.send(s,{'v':1,'id':'2','op':'poll','args':{'sessionId':session,'limit':1,'byteLimit':1024}});await self.recv(s)
            s.close();await t;c,n=await self.opened(h);self.assertEqual((await self.poll(h,c,n))['result']['cursor']['position'],'0')
        self.run_async(body)
    def test_idle_connection_expires(self):
        async def body(h):
            s,t=await self.connected(h);await self.recv(s);await asyncio.wait_for(t,1);s.close();self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_socket_wait_notification(self):
        async def body(h):
            s,t,_,session=await self.open_remote(h)
            await self.send(s,{'v':1,'id':'2','op':'poll','args':{'sessionId':session,'limit':1,'byteLimit':1024}});r=await self.recv(s)
            self.emit()
            await self.send(s,{'v':1,'id':'3','op':'wait','args':{'sessionId':session,'ticket':r['value']['ticket']}})
            r=await self.recv(s);self.assertEqual(r['value']['result']['reason'],'changed');s.close();await t
        self.run_async(body)
    def test_host_close_closes_idle_attached_transport_promptly(self):
        async def body(h):
            s,t=await self.connected(h);await self.recv(s);h.close()
            await asyncio.wait_for(asyncio.shield(t),.1)
            self.assertEqual(await asyncio.get_running_loop().sock_recv(s,1),b'');s.close()
        self.run_async(body)
