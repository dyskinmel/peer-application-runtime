import asyncio,socket,unittest
from unittest.mock import patch
from product.wp09 import par_connectivity as api
from fixtures import settled

class TcpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertTrue(callable(getattr(api,'SocketConnection',None)),'numeric TCP and bounded socket adapter are not implemented')
        self.connections=[];self.peers=[]
    async def asyncTearDown(self):
        for c in getattr(self,'connections',[]):await c.close()
        for s in getattr(self,'peers',[]):s.close()
    def pair(self,**kw):
        a,b=socket.socketpair();b.setblocking(False);c=api.SocketConnection(a,**kw);self.connections.append(c);self.peers.append(b);return c,b
    async def test_real_socketpair_exact_read(self):
        c,b=self.pair();await asyncio.get_running_loop().sock_sendall(b,b'abcdef');self.assertEqual(await c.read_exact(3),b'abc');self.assertEqual(await c.read_exact(3),b'def')
    async def test_real_socketpair_exact_write(self):
        c,b=self.pair();await c.write(b'abc');self.assertEqual(await asyncio.get_running_loop().sock_recv(b,3),b'abc')
    async def test_partial_read_detects_eof(self):
        c,b=self.pair();b.send(b'a');b.close()
        with self.assertRaises(api.ConnectivityError) as cm:await c.read_exact(2)
        self.assertEqual(cm.exception.code,'EOF')
    async def test_read_chunk_budget(self):
        c,b=self.pair(max_chunk=4)
        with self.assertRaises(api.ConnectivityError) as cm:await c.read_exact(5)
        self.assertEqual(cm.exception.code,'IO_BUDGET')
    async def test_write_chunk_budget(self):
        c,b=self.pair(max_chunk=4)
        with self.assertRaises(api.ConnectivityError):await c.write(b'12345')
    async def test_total_read_budget_is_not_per_call(self):
        c,b=self.pair(max_total_read=5);b.send(b'12345');self.assertEqual(await c.read_exact(3),b'123')
        with self.assertRaises(api.ConnectivityError):await c.read_exact(3)
    async def test_total_write_budget_is_not_per_call(self):
        c,b=self.pair(max_total_write=5);await c.write(b'123')
        with self.assertRaises(api.ConnectivityError):await c.write(b'456')
    async def test_cancelled_read_keeps_conservative_byte_charge(self):
        c,b=self.pair(max_total_read=4);t=asyncio.create_task(c.read_exact(4));await settled(lambda:c.io_state()['read_busy']);t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
        with self.assertRaises(api.ConnectivityError):await c.read_exact(1)
    async def test_concurrent_reads_refused(self):
        c,b=self.pair();t=asyncio.create_task(c.read_exact(2));await settled(lambda:c.io_state()['read_busy'])
        with self.assertRaises(api.ConnectivityError) as cm:await c.read_exact(1)
        self.assertEqual(cm.exception.code,'IO_BUSY');b.send(b'ab');self.assertEqual(await t,b'ab')
    async def test_close_unblocks_read_and_closes_descriptor(self):
        c,b=self.pair();t=asyncio.create_task(c.read_exact(1));await settled(lambda:c.io_state()['read_busy']);await c.close()
        with self.assertRaises(api.ConnectivityError) as cm:await t
        self.assertEqual(cm.exception.code,'CLOSED');self.assertTrue(c.io_state()['closed']);self.assertEqual(c.io_state()['pending'],0)
    async def test_close_is_idempotent(self):
        c,b=self.pair();await c.close();await c.close()
        with self.assertRaises(api.ConnectivityError):await c.write(b'x')
    async def test_io_timeout_is_bounded(self):
        c,b=self.pair(io_timeout=0.01)
        with self.assertRaises(api.ConnectivityError) as cm:await c.read_exact(1)
        self.assertEqual(cm.exception.code,'IO_DEADLINE');self.assertFalse(c.io_state()['read_busy'])
    async def test_io_rejects_bool_sizes_and_untyped_write(self):
        c,b=self.pair()
        with self.assertRaises(api.ConnectivityError):await c.read_exact(True)
        with self.assertRaises(api.ConnectivityError):await c.write('secret')
    async def test_unix_socket_not_reported_internet_direct(self):
        c,b=self.pair();self.assertEqual(c.observed_path,'local-fixture')
    async def test_adapter_refuses_hostname_before_socket_creation(self):
        target=api.DialTarget('tcp','peer.invalid',443,'peer.invalid','p','manual',0)
        with patch('product.wp09.par_connectivity.tcp.socket.socket') as make:
            with self.assertRaises(api.ConnectivityError):await api.NumericTcpDialer().dial(target,asyncio.Event())
            make.assert_not_called()
    async def test_adapter_refuses_unsupported_scheme(self):
        target=api.DialTarget('quic','8.8.8.8',443,None,'p','manual',0)
        with self.assertRaises(api.ConnectivityError) as cm:await api.NumericTcpDialer().dial(target,asyncio.Event())
        self.assertEqual(cm.exception.code,'ADAPTER_UNAVAILABLE')
    async def test_adapter_precancel_never_allocates_socket(self):
        target=api.DialTarget('tcp','8.8.8.8',443,None,'p','manual',0);stop=asyncio.Event();stop.set()
        with patch('product.wp09.par_connectivity.tcp.socket.socket') as make:
            with self.assertRaises(api.ConnectivityError):await api.NumericTcpDialer().dial(target,stop)
            make.assert_not_called()
    async def test_native_numeric_tuple_wiring_and_failure_closes_socket(self):
        # Controlled sock_connect proves tuple wiring only, not real AF_INET dial.
        class Raw:
            def __init__(self):self.closed=0
            def setblocking(self,value):self.blocking=value
            def close(self):self.closed+=1
        raw=Raw();seen=[]
        async def connect(s,address):seen.append(address);raise OSError('synthetic')
        loop=asyncio.get_running_loop();target=api.DialTarget('tcp','2606:4700:4700::1111',443,'peer.invalid','p','manual',0)
        with patch('product.wp09.par_connectivity.tcp.socket.socket',return_value=raw) as make,patch.object(loop,'sock_connect',new=connect):
            with self.assertRaises(OSError):await api.NumericTcpDialer().dial(target,asyncio.Event())
            self.assertEqual(make.call_args.args,(socket.AF_INET6,socket.SOCK_STREAM));self.assertEqual(seen,[('2606:4700:4700::1111',443,0,0)])
        self.assertEqual(raw.closed,1)
