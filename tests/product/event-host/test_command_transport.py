"""Separate capability/protocol, actual AF_UNIX framing and journal effects."""
import asyncio, importlib, json, socket, struct
from test_events import EventTest
from test_commands import CommandTests
from test_transport import TransportTests

class CommandSocketTests(EventTest):
    run_async=CommandTests.run_async
    send=TransportTests.send
    recv=TransportTests.recv
    def setUp(self):
        super().setUp()
        self.commands=importlib.import_module('product.wp10.commands')
        try:self.transport=importlib.import_module('product.wp10.command_transport')
        except ModuleNotFoundError:self.transport=None
        self.assertTrue(self.transport is not None and hasattr(self.transport,'serve_commands_connected'),
                        'separate command descriptor transport is not implemented')
        self.create()
    async def connected(self,c,allow=True):
        a,b=socket.socketpair();b.setblocking(False)
        t=asyncio.create_task(self.transport.serve_commands_connected(c,a,allow_publish=allow,read_timeout=.5,write_timeout=.5))
        hello=await self.recv(b);self.assertEqual(hello['protocol'],'par-local-event-commands-0040')
        return b,t,hello
    def args(self,hello):
        return {'context':hello['context'],'operationId':'01'*16,'payload':{'body':{'kind':'text','value':'typed over fd'},'count':{'kind':'uint64','value':'18446744073709551615'}},'parents':[]}
    def test_real_socket_publish_then_inquire(self):
        async def body(h,c):
            s,t,hello=await self.connected(c)
            try:
                a=self.args(hello);await self.send(s,{'v':1,'id':'1','op':'publish','args':a});r=await self.recv(s)
                self.assertEqual(r['value']['kind'],'local-committed')
                await self.send(s,{'v':1,'id':'2','op':'inquire','args':{'context':hello['context'],'operationId':a['operationId']}})
                self.assertEqual((await self.recv(s))['value'],r['value']);self.assertEqual(self.journal.inspect()['nonces'],1)
            finally:s.close();await t
        self.run_async(body)
    def test_inquiry_only_fd_cannot_publish(self):
        async def body(h,c):
            s,t,hello=await self.connected(c,False)
            try:
                self.assertEqual(hello['context']['authority'],'inquire-only')
                await self.send(s,{'v':1,'id':'1','op':'publish','args':self.args(hello)})
                self.assertEqual((await self.recv(s))['value']['code'],'COMMAND_NOT_AUTHORIZED')
                self.assertEqual(self.journal.inspect()['nonces'],0)
            finally:s.close();await t
        self.run_async(body)
    def test_ack_cannot_cross_to_command_port(self):
        async def body(h,c):
            s,t,_=await self.connected(c)
            try:
                await self.send(s,{'v':1,'id':'1','op':'ack','args':{}});await asyncio.wait_for(t,1)
                self.assertEqual(self.journal.inspect()['consumers'],0);self.assertEqual(c.stats()['channels'],0)
            finally:s.close()
        self.run_async(body)
    def test_wrong_frame_version_has_no_effect(self):
        async def body(h,c):
            s,t,hello=await self.connected(c)
            try:
                await self.send(s,{'v':2,'id':'1','op':'publish','args':self.args(hello)});await asyncio.wait_for(t,1)
                self.assertEqual(self.journal.inspect()['nonces'],0)
            finally:s.close()
        self.run_async(body)
    def test_duplicate_frame_key_refused(self):
        async def body(h,c):
            s,t,_=await self.connected(c)
            try:
                raw=b'{"v":1,"id":"1","id":"2","op":"publish","args":{}}'
                await asyncio.get_running_loop().sock_sendall(s,struct.pack('!I',len(raw))+raw)
                await asyncio.wait_for(t,1);self.assertEqual(self.journal.inspect()['nonces'],0)
            finally:s.close()
        self.run_async(body)
    def test_oversize_frame_refused_before_body(self):
        async def body(h,c):
            s,t,_=await self.connected(c)
            try:
                await asyncio.get_running_loop().sock_sendall(s,struct.pack('!I',65537))
                await asyncio.wait_for(t,1);self.assertEqual(self.journal.inspect()['nonces'],0)
            finally:s.close()
        self.run_async(body)
    def test_reused_transport_id_cannot_replay_command(self):
        async def body(h,c):
            s,t,hello=await self.connected(c)
            try:
                a=self.args(hello);await self.send(s,{'v':1,'id':'1','op':'publish','args':a});await self.recv(s)
                a['operationId']='02'*16;await self.send(s,{'v':1,'id':'1','op':'publish','args':a});await asyncio.wait_for(t,1)
                self.assertEqual(self.journal.inspect()['events'],1)
            finally:s.close()
        self.run_async(body)
    def test_parent_close_closes_idle_fd(self):
        async def body(h,c):
            s,t,_=await self.connected(c)
            try:
                h.close();await asyncio.wait_for(asyncio.shield(t),.2)
                self.assertEqual(await asyncio.get_running_loop().sock_recv(s,1),b'')
            finally:s.close()
        self.run_async(body)
    def test_socket_invalid_payload_rejected_without_nonce(self):
        async def body(h,c):
            s,t,hello=await self.connected(c)
            try:
                a=self.args(hello);a['payload']['count']['value']=1
                await self.send(s,{'v':1,'id':'1','op':'publish','args':a})
                self.assertEqual((await self.recv(s))['value']['code'],'COMMAND_INPUT_INVALID')
                self.assertEqual(self.journal.inspect()['nonces'],0)
            finally:s.close();await t
        self.run_async(body)
