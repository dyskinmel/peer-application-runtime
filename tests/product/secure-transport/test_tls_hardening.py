import asyncio,ssl,socket,unittest
from unittest.mock import patch
from secure_support import API

class HardeningTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.load();self.raw=[];self.streams=[]
    async def asyncTearDown(self):await self.cleanup()
    async def raw_client(self,*,alpn=None,cert=True,version=ssl.TLSVersion.TLSv1_3):
        a,b=socket.socketpair();self.raw.extend((a,b));b.setblocking(False)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version=context.maximum_version=version
        context.load_verify_locations(cafile=str(self.pki.path/'ca.pem'))
        if cert:context.load_cert_chain(str(self.pki.path/'client.pem'),str(self.pki.path/'client.key'))
        if alpn is not None:context.set_alpn_protocols([alpn])
        async def peer():
            try:
                r,w=await asyncio.open_connection(sock=b,ssl=context,server_hostname='server.test',ssl_handshake_timeout=.4)
                try:await asyncio.wait_for(r.read(1),.6)
                finally:
                    w.close()
                    try:await w.wait_closed()
                    except (OSError,ssl.SSLError):pass
            except (OSError,TimeoutError):b.close()
        task=asyncio.create_task(peer())
        try:
            with self.assertRaises(self.m.TransportError):await self.m.TLSStream.open(a,self.pki.config(self.m,True),limits=self.m.Limits(timeout=.5))
        finally:await asyncio.gather(task,return_exceptions=True)
    async def test_no_alpn_rejected(self):await self.raw_client()
    async def test_wrong_alpn_rejected(self):await self.raw_client(alpn='unrelated/1')
    async def test_missing_client_certificate_rejected(self):await self.raw_client(alpn=self.m.ALPN,cert=False)
    async def test_tls12_downgrade_rejected(self):await self.raw_client(alpn=self.m.ALPN,version=ssl.TLSVersion.TLSv1_2)
    async def test_too_small_chunk_rejected_at_configuration(self):
        for n in (1,2,3):
            with self.assertRaises(self.m.TransportError):self.m.Limits(chunk=n)
    async def test_close_timeout_does_not_orphan_waiter(self):
        s,c=await self.good_pair(limits=self.m.Limits(cleanup_timeout=.03));pending=[]
        async def hanging():
            pending.append(asyncio.current_task())
            await asyncio.Event().wait()
        # Inject a non-completing close callback at the real TLS writer boundary.
        with patch.object(c._writer,'wait_closed',side_effect=hanging):
            await c.close();await asyncio.sleep(0)
            live=[t for t in pending if not t.done()]
            # Capture evidence then clean injected tasks so test failure cannot leak.
            for t in live:t.cancel()
            await asyncio.gather(*live,return_exceptions=True)
            self.assertEqual(live,[],'wait_closed task leaked after timeout')
    async def test_close_cancellation_does_not_orphan_waiter(self):
        s,c=await self.good_pair();pending=[];ready=asyncio.Event()
        async def hanging():pending.append(asyncio.current_task());ready.set();await asyncio.Event().wait()
        with patch.object(c._writer,'wait_closed',side_effect=hanging):
            task=asyncio.create_task(c.close());await ready.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            live=[t for t in pending if not t.done()]
            for t in live:t.cancel()
            await asyncio.gather(*live,return_exceptions=True)
            self.assertEqual(live,[],'wait_closed task leaked after cancellation')
    async def test_absolute_deadline_not_extended_by_frame_boundaries(self):
        s,c=await self.good_pair(limits=self.m.Limits(timeout=.15));f=self.m.FramedChannel(c);g=self.m.FramedChannel(s)
        await asyncio.gather(f.send(b'A',8),g.receive(8))
        await asyncio.sleep(.17)
        with self.assertRaises(self.m.TransportError):await f.send(b'B',8)
