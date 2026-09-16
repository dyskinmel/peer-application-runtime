import asyncio,struct,unittest
from secure_support import API
class FrameTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.load();self.raw=[];self.streams=[]
    async def asyncTearDown(self):await self.cleanup()
    async def frames(self,**kw):
        s,c=await self.good_pair(**kw);return self.m.FramedChannel(s),self.m.FramedChannel(c)
    async def test_binary_roundtrip(self):
        s,c=await self.frames();raw=bytes(range(256))*100
        await c.send(raw,32768);self.assertEqual(await s.receive(32768),raw)
    async def test_multiple_fragmented_frames(self):
        s,c=await self.frames()
        for raw in (b'x',b'ab',b'\x00'*1000):
            await c.send(raw,1024);self.assertEqual(await s.receive(1024),raw)
    async def test_empty_frame_denied_before_payload(self):
        s,c=await self.good_pair();await c.write(struct.pack('!I',0));f=self.m.FramedChannel(s)
        with self.assertRaises(self.m.TransportError):await f.receive(1024)
    async def test_oversize_header_denied_without_body(self):
        s,c=await self.good_pair();await c.write(struct.pack('!I',2**32-1));f=self.m.FramedChannel(s)
        with self.assertRaises(self.m.TransportError) as cm:await f.receive(1024)
        self.assertEqual(cm.exception.code,'FRAME_LIMIT');self.assertTrue(s.closed)
    async def test_truncated_body_not_success(self):
        s,c=await self.good_pair();await c.write(struct.pack('!I',8)+b'abc');c.abort()
        with self.assertRaises(self.m.TransportError):await self.m.FramedChannel(s).receive(1024)
    async def test_outgoing_frame_budget(self):
        s,c=await self.frames()
        with self.assertRaises(self.m.TransportError):await c.send(b'ab',1)
    async def test_wrong_input_type(self):
        s,c=await self.frames()
        with self.assertRaises(self.m.TransportError):await c.send('string',1024)
    async def test_frame_count_not_unlimited(self):
        s,c=await self.frames(limits=self.m.Limits(max_frames=1))
        await c.send(b'a',16);self.assertEqual(await s.receive(16),b'a')
        with self.assertRaises(self.m.TransportError):await c.send(b'b',16)
    async def test_frame_deadline_not_reset_by_fragments(self):
        s,c=await self.good_pair(limits=self.m.Limits(timeout=.12));f=self.m.FramedChannel(s)
        async def drip():
            try:
                for byte in struct.pack('!I',4)+b'data':await c.write(bytes([byte]));await asyncio.sleep(.035)
            except self.m.TransportError:pass
        task=asyncio.create_task(drip())
        with self.assertRaises(self.m.TransportError):await f.receive(1024)
        await task
