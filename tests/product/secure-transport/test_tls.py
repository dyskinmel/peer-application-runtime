import asyncio, dataclasses, os, socket, ssl, time, unittest
from unittest.mock import patch
from secure_support import API

class TLSConfigTests(API,unittest.TestCase):
    def setUp(self):self.load()
    def test_context_tls13_only(self):
        for side in (False,True):
            c=self.pki.config(self.m,side).context()
            self.assertEqual(c.minimum_version,ssl.TLSVersion.TLSv1_3)
            self.assertEqual(c.maximum_version,ssl.TLSVersion.TLSv1_3)
    def test_mutual_cert_required(self):
        for side in (False,True):self.assertEqual(self.pki.config(self.m,side).context().verify_mode,ssl.CERT_REQUIRED)
    def test_hostname_check_enabled_for_client(self):
        self.assertTrue(self.pki.config(self.m,False).context().check_hostname)
    def test_strict_x509_enabled(self):
        self.assertTrue(self.pki.config(self.m,True).context().verify_flags & ssl.VERIFY_X509_STRICT)
    def test_keylog_environment_not_adopted(self):
        path=self.pki.path/'must-not-create.log'
        with patch.dict(os.environ,{'SSLKEYLOGFILE':str(path)}):
            self.assertIsNone(self.pki.config(self.m,False).context().keylog_filename)
        self.assertFalse(path.exists())
    def test_config_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):self.pki.config(self.m,False).peer_sha256='0'*64
    def test_bad_pin_rejected(self):
        for value in ('',True,'g'*64,'0'*63,None):
            with self.subTest(v=value),self.assertRaises(self.m.TransportError):self.pki.config(self.m,False,peer_sha256=value)
    def test_hostname_required(self):
        for value in (None,'','https://server.test','server.test/','*',True):
            with self.subTest(v=value),self.assertRaises(self.m.TransportError):self.pki.config(self.m,False,server_hostname=value)
    def test_no_ambient_trust(self):
        with self.assertRaises(self.m.TransportError):self.pki.config(self.m,False,ca_file='')
    def test_limits_strict_integers(self):
        for v in (True,0,-1,1.2,2**32):
            with self.subTest(v=v),self.assertRaises(self.m.TransportError):self.m.Limits(max_frame=v)
    def test_deadlines_finite(self):
        for v in (True,0,-1,float('nan'),float('inf'),61):
            with self.subTest(v=v),self.assertRaises(self.m.TransportError):self.m.Limits(timeout=v)
    def test_no_session_tickets(self):
        self.assertEqual(self.pki.config(self.m,True).context().num_tickets,0)

class TLSTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.load();self.raw=[];self.streams=[]
    async def asyncTearDown(self):await self.cleanup()
    async def test_real_tls13_both_peer_certificates_verified(self):
        server,client=await self.good_pair()
        self.assertEqual(server.peer_certificate_sha256,self.pki.pin('client'))
        self.assertEqual(client.peer_certificate_sha256,self.pki.pin('server'))
        self.assertEqual(client.tls_version,'TLSv1.3');self.assertEqual(server.alpn,self.m.ALPN)
    async def test_real_encrypted_bidirectional_payload(self):
        s,c=await self.good_pair();payload=b'private-payload-'*300
        await c.write(payload);self.assertEqual(await s.read_exact(len(payload)),payload)
        await s.write(b'ok');self.assertEqual(await c.read_exact(2),b'ok')
    async def test_wrong_server_pin_rejected(self):
        rows=await self.pair(client=self.pki.config(self.m,False,peer_sha256='0'*64))
        self.assertIsInstance(rows[1],self.m.TransportError);self.assertEqual(rows[1].code,'TLS_PIN')
    async def test_wrong_client_pin_rejected(self):
        rows=await self.pair(server=self.pki.config(self.m,True,peer_sha256='0'*64))
        self.assertIsInstance(rows[0],self.m.TransportError);self.assertEqual(rows[0].code,'TLS_PIN')
    async def test_wrong_hostname_rejected(self):
        rows=await self.pair(client=self.pki.config(self.m,False,server_hostname='else.test'))
        self.assertIsInstance(rows[1],self.m.TransportError)
    async def test_expired_certificate_rejected(self):
        rows=await self.pair(server=self.pki.config(self.m,True,cert_file=self.pki.path/'expired.pem',key_file=self.pki.path/'expired.key'),
                             client=self.pki.config(self.m,False,peer_sha256=self.pki.pin('expired')))
        self.assertIsInstance(rows[1],self.m.TransportError)
    async def test_unknown_ca_rejected(self):
        # A leaf from this test PKI is not the trusted issuing root.
        rows=await self.pair(client=self.pki.config(self.m,False,ca_file=self.pki.path/'other.pem'))
        self.assertIsInstance(rows[1],self.m.TransportError)
    async def test_wrong_client_eku_rejected(self):
        rows=await self.pair(client=self.pki.config(self.m,False,cert_file=self.pki.path/'server.pem',key_file=self.pki.path/'server.key'),
                             server=self.pki.config(self.m,True,peer_sha256=self.pki.pin('server')))
        self.assertIsInstance(rows[0],self.m.TransportError)
    async def test_handshake_deadline_closes_socket(self):
        a,b=socket.socketpair();self.raw.extend((a,b));start=time.monotonic()
        with self.assertRaises(self.m.TransportError) as cm:
            await self.m.TLSStream.open(a,self.pki.config(self.m,False),limits=self.m.Limits(timeout=.08))
        self.assertEqual(cm.exception.code,'TLS_DEADLINE');self.assertLess(time.monotonic()-start,1)
        self.assertEqual(a.fileno(),-1)
    async def test_task_cancel_during_handshake_closes_socket(self):
        a,b=socket.socketpair();self.raw.extend((a,b))
        task=asyncio.create_task(self.m.TLSStream.open(a,self.pki.config(self.m,False)))
        await asyncio.sleep(.02);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(a.fileno(),-1)
    async def test_pre_cancel_does_not_send_client_hello(self):
        a,b=socket.socketpair();self.raw.extend((a,b));cancel=asyncio.Event();cancel.set()
        with self.assertRaises(self.m.TransportError):await self.m.TLSStream.open(a,self.pki.config(self.m,False),cancel=cancel)
        self.assertEqual(a.fileno(),-1);b.setblocking(False);self.assertEqual(b.recv(100),b'')
    async def test_event_cancel_during_handshake_closes_socket(self):
        a,b=socket.socketpair();self.raw.extend((a,b));cancel=asyncio.Event()
        task=asyncio.create_task(self.m.TLSStream.open(a,self.pki.config(self.m,False),cancel=cancel))
        await asyncio.sleep(.02);cancel.set()
        with self.assertRaises(self.m.TransportError) as cm:await task
        self.assertEqual(cm.exception.code,'CANCELLED');self.assertEqual(a.fileno(),-1)
    async def test_eof_handshake_not_success(self):
        a,b=socket.socketpair();self.raw.extend((a,b));b.close()
        with self.assertRaises(self.m.TransportError):await self.m.TLSStream.open(a,self.pki.config(self.m,False))
    async def test_plaintext_peer_not_tls_success(self):
        a,b=socket.socketpair();self.raw.extend((a,b));b.sendall(b'plaintext-not-tls\n')
        with self.assertRaises(self.m.TransportError):await self.m.TLSStream.open(a,self.pki.config(self.m,False))
    async def test_read_deadline_is_terminal(self):
        s,c=await self.good_pair(limits=self.m.Limits(timeout=.08))
        with self.assertRaises(self.m.TransportError) as cm:await c.read_exact(1)
        self.assertEqual(cm.exception.code,'IO_DEADLINE');self.assertTrue(c.closed)
    async def test_read_cancel_is_terminal(self):
        s,c=await self.good_pair();task=asyncio.create_task(c.read_exact(1));await asyncio.sleep(.02);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(c.closed)
    async def test_concurrent_reader_rejected(self):
        s,c=await self.good_pair();task=asyncio.create_task(c.read_exact(1));await asyncio.sleep(.01)
        with self.assertRaises(self.m.TransportError) as cm:await c.read_exact(1)
        self.assertEqual(cm.exception.code,'IO_BUSY');await s.write(b'x');self.assertEqual(await task,b'x')
    async def test_byte_budget(self):
        s,c=await self.good_pair(limits=self.m.Limits(max_total_bytes=64))
        with self.assertRaises(self.m.TransportError):await c.write(b'x'*65)
    async def test_no_io_after_close(self):
        s,c=await self.good_pair();await asyncio.gather(s.close(),c.close())
        with self.assertRaises(self.m.TransportError):await c.write(b'x')
        self.assertTrue(s.closed and c.closed)
    async def test_no_file_descriptor_growth(self):
        before=len(os.listdir('/proc/self/fd'))
        for _ in range(8):
            s,c=await self.good_pair();await asyncio.gather(s.close(),c.close())
        await asyncio.sleep(.02);self.assertLessEqual(len(os.listdir('/proc/self/fd')),before)
