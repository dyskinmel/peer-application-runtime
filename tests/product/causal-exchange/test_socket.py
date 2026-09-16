import socket,struct,threading,time,copy
from pathlib import Path
from exchange_support import ExchangeTest,h
from par_keeper_service.transport import receive,send

class SocketTests(ExchangeTest):
    def test_need_over_real_socket(self):
        a,b=self.fill();self.start_server();r=self.rpc(lambda:self.client().need([self.cid(a[0])]))
        self.assertEqual(r[1][0][1][1],self.eid(a[0]))
    def test_get_over_real_socket(self):
        a,b=self.fill();self.start_server();cli=self.client();r=self.rpc(lambda:cli.need([self.cid(a[0])]))
        self.assertEqual(self.rpc(lambda:cli.fetch(r[0],r[1][0][1])),a)
    def test_have_pages_over_socket(self):
        self.fill();self.start_server();cli=self.client();r=self.rpc(lambda:cli.have(limit=1));n=self.rpc(lambda:cli.have(snapshot=r[0],offset=r[3],limit=1))
        self.assertEqual(n[4],2);self.assertIsNone(n[3])
    def test_unauthorized_reader_refused(self):
        self.start_server();self.reject_exchange('REMOTE_NOT_AUTHORIZED',lambda:self.rpc(lambda:self.client(self.s.devices[2]).need([h('x')])))
    def test_requester_key_mismatch(self):
        self.start_server();d=dict(self.reader,seed=h('wrong'))
        self.reject_exchange('REMOTE_REQUEST_AUTH',lambda:self.rpc(lambda:self.client(d).need([h('x')])))
    def test_wrong_server_pin_refused_before_request(self):
        self.start_server();cli=self.client();cli.public=self.p.sign_public(h('wrong'))
        self.reject_exchange('HELLO_AUTH',lambda:self.rpc(lambda:cli.need([h('x')])));self.assertEqual(self.server.counts['completed'],0)
    def test_old_snapshot_get_refused(self):
        a,b=self.fill();self.start_server();cli=self.client();r=self.rpc(lambda:cli.need([self.cid(a[0])]))
        self.receive(self.change('c',seq=3,parents=[self.cid(b[0])],previous=self.eid(b[0])))
        self.reject_exchange('REMOTE_STALE_VIEW',lambda:self.rpc(lambda:cli.fetch(r[0],r[1][0][1])))
    def test_incomplete_header_does_not_stall_other_client(self):
        self.start_server(deadline_ms=300);s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path));self.addCleanup(s.close)
        for _ in range(5):self.server.poll(.005)
        s.sendall(b'\0\0');r=self.rpc(lambda:self.client(timeout=1).need([h('x')]))
        self.assertIsNone(r[1][0][1]);end=time.monotonic()+.4
        while time.monotonic()<end:self.server.poll(.01)
        self.assertEqual(len(self.server.connections),0);self.assertGreaterEqual(self.server.counts['expired'],1)
    def test_oversized_frame_refused_without_allocation(self):
        self.start_server();s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path));self.addCleanup(s.close)
        for _ in range(5):self.server.poll(.005)
        s.sendall(struct.pack('>I',self.x.MAX_REQUEST+1))
        for _ in range(5):self.server.poll(.005)
        self.assertFalse(self.server.connections)
    def test_disconnected_peer_releases_connection_slot(self):
        self.start_server(max_connections=1);s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path))
        for _ in range(4):self.server.poll(.005)
        s.close()
        for _ in range(4):self.server.poll(.005)
        self.assertFalse(self.server.connections);self.rpc(lambda:self.client().need([h('x')]))
    def test_close_is_idempotent_and_removes_own_socket(self):
        self.start_server();self.server.close();self.server.close();self.assertFalse(self.socket_path.exists())
    def test_nonowner_close_cannot_mutate_server(self):
        self.start_server();errors=[]
        def wrong():
            try:self.server.close()
            except Exception as e:errors.append(e)
        t=threading.Thread(target=wrong);t.start();t.join()
        self.assertEqual(errors[0].code,'WRONG_OWNER');self.assertFalse(self.server.closed)
    def test_unrecognized_method_refused_before_connect(self):
        self.reject_exchange('METHOD_DENIED',lambda:self.client().call('commit',None))
    def test_real_receiver_pending_only(self):
        from product.wp04.inbox import SyncInbox
        a,b=self.fill();self.start_server();cli=self.client()
        sink=SyncInbox.create(self.root.parent/'sink',self.db,**self.scope);self.addCleanup(sink.close)
        r=self.rpc(lambda:cli.need([self.cid(b[0])]))
        pair=self.rpc(lambda:cli.fetch(r[0],r[1][0][1]));ack=sink.receive(*pair)
        self.assertEqual(ack['state'],'PENDING_BYTES');self.assertFalse(ack['applied'])
        self.assertEqual(sink.needed(),[self.cid(a[0]).hex()])
        missing=[bytes.fromhex(x) for x in sink.needed()];r=self.rpc(lambda:cli.need(missing))
        pair=self.rpc(lambda:cli.fetch(r[0],r[1][0][1]));sink.receive(*pair)
        self.assertEqual(sink.inspect(self.eid(b[0]))['state'],'READY_FOR_CORE');self.assertEqual(sink.validate(self.eid(b[0]))['state'],'CORE_BLOCKED')
        before=sink.pin();sink.receive(*pair);self.assertEqual(before,sink.pin())
    def test_permission_change_between_dispatch_and_send_drops_reply(self):
        a,b=self.fill();self.start_server(send_chunk=32);cli=self.client();result=[];errors=[]
        def run():
            try:result.append(cli.need([self.cid(a[0])]))
            except Exception as e:errors.append(e)
        t=threading.Thread(target=run);t.start();end=time.monotonic()+5;changed=False
        while t.is_alive() and time.monotonic()<end:
            self.server.poll(.002)
            if not changed and any(c.phase=='response' and c.guard is not None for c in self.server.connections.values()):
                self.same_epoch();changed=True
        t.join(.1);self.assertFalse(t.is_alive());self.assertTrue(changed);self.assertFalse(result);self.assertEqual(errors[0].code,'OUTCOME_UNKNOWN')
    def test_corruption_after_dispatch_drops_reply(self):
        a,b=self.fill();self.start_server(send_chunk=32);cli=self.client();result=[];errors=[]
        def run():
            try:result.append(cli.need([self.cid(a[0])]))
            except Exception as e:errors.append(e)
        t=threading.Thread(target=run);t.start();end=time.monotonic()+5;changed=False
        while t.is_alive() and time.monotonic()<end:
            self.server.poll(.002)
            if not changed and any(c.phase=='response' and c.guard is not None for c in self.server.connections.values()):
                (self.path/'records'/(self.eid(a[0]).hex()+'.cbor')).write_bytes(b'bad');changed=True
        t.join(.1);self.assertFalse(t.is_alive());self.assertTrue(changed);self.assertFalse(result);self.assertEqual(errors[0].code,'OUTCOME_UNKNOWN')
