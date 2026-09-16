"""Actual private socket/process faults; OS-error injections are named separately."""
import errno,json,os,signal,socket,struct,time
from unittest.mock import patch
from service_support import ServiceTest,h

class ServiceFaults(ServiceTest):
    def test_denied_os_peer_does_not_stop_service(self):
        self.start_local();c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            c.connect(str(self.socket_path))
            with patch('par_keeper_service.server.peer_uid',side_effect=self.ipc.ServiceError('PEER_IDENTITY')):
                self.server.poll(.02)
            self.assertEqual(self.server.diagnostics()['active_connections'],0)
        finally:c.close()
        c,hello=self.connect_local();self.assertEqual(self.ipc.check_hello(self.p,self.kp,hello)[2],self.kp)
    def test_socket_send_error_releases_pin(self):
        self.start_local(send_chunk=1);c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        for _ in range(4):self.server.poll(.01)
        self.assertEqual(len(self.keeper._pins),1);c.shutdown(socket.SHUT_RDWR);c.close();self.pump()
        self.assertEqual(len(self.keeper._pins),0)
    def test_trickle_does_not_extend_deadline(self):
        self.start_local(deadline_ms=100);c,hello=self.connect_local()
        for b in (b'\x00',b'\x00',b'\x03'):
            c.sendall(b);self.server.poll(0);time.sleep(.04)
        self.server.poll(0);self.assertEqual(self.server.diagnostics()['expired'],1)
        self.assertEqual(self.server.diagnostics()['active_connections'],0)
    def test_oversize_header_rejected_without_body(self):
        self.start_local();c,hello=self.connect_local();c.sendall(struct.pack('>I',self.ipc.MAX_REQUEST+1));self.pump()
        self.assertEqual(c.recv(1),b'');self.assertEqual(self.server.diagnostics()['active_connections'],0)
    def test_zero_header_rejected(self):
        self.start_local();c,hello=self.connect_local();c.sendall(bytes(4));self.pump();self.assertEqual(c.recv(1),b'')
    def test_partial_request_eof(self):
        self.start_local();c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST)[:-2]);c.shutdown(socket.SHUT_WR);self.pump()
        self.assertEqual(c.recv(1),b'');self.assertEqual(len(self.keeper._pins),0)
    def test_coalesced_requests_never_dispatch_twice(self):
        self.start_local();c,hello=self.connect_local();q=self.request_raw(hello,'status');data=self.ipc.frame(q,self.ipc.MAX_REQUEST)
        c.sendall(data+data);self.pump()
        raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.assertIsInstance(self.ipc.check_response(self.p,self.kp,hello,q,raw),list)
        self.assertEqual(self.server.diagnostics()['completed'],1)
    def test_fragmented_frame(self):
        self.start_local();c,hello=self.connect_local();q=self.request_raw(hello,'status')
        for x in self.ipc.frame(q,self.ipc.MAX_REQUEST):c.sendall(bytes([x]));self.server.poll(0)
        self.pump();raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.assertIsInstance(self.ipc.check_response(self.p,self.kp,hello,q,raw),list)
    def test_bad_signature_response_no_secret_or_traceback(self):
        from par_wire.codec import encode,decode
        self.start_local();c,hello=self.connect_local();o=decode(self.request_raw(hello));o[1]=bytes(64);q=encode(o)
        c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump();raw=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.ipc.check_response(self.p,self.kp,hello,q,raw))
        self.assertNotIn(self.ks,raw);self.assertNotIn(b'Traceback',raw);self.assertNotIn(str(self.path).encode(),raw)
    def test_connection_replay_rejected(self):
        self.start_local();c,hello=self.connect_local();q=self.request_raw(hello,'status');c.close();self.pump()
        c,hello2=self.connect_local();self.assertNotEqual(hello,hello2);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        r=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.ipc.check_response(self.p,self.kp,hello2,q,r))
    def test_max_connections_and_buffer_bound(self):
        self.start_local(max_connections=2);clients=[]
        try:
            for _ in range(4):
                c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.settimeout(.3);c.connect(str(self.socket_path));clients.append(c);self.server.poll(0)
            d=self.server.diagnostics();self.assertEqual(d['active_connections'],2);self.assertEqual(d['overload'],2)
            self.assertLessEqual(d['peak_buffered_bytes'],2*(self.ipc.MAX_RESPONSE+self.ipc.MAX_REQUEST+8))
        finally:
            for c in clients:c.close()
        self.pump();self.assertEqual(self.server.diagnostics()['active_connections'],0)
    def test_slow_peer_does_not_block_other_process_client(self):
        self.start_process();c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            c.connect(str(self.socket_path));self.ipc.receive(c,self.ipc.MAX_HELLO,time.monotonic()+1)
            start=time.monotonic();self.assertFalse(self.client.status(self.lid)['product_qualified']);self.assertLess(time.monotonic()-start,1.5)
        finally:c.close()
    def test_timeout_releases_pending_response_pin(self):
        self.start_local(send_chunk=1,deadline_ms=150);c,hello=self.connect_local();q=self.request_raw(hello);c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        for _ in range(4):self.server.poll(0)
        self.assertEqual(len(self.keeper._pins),1);time.sleep(.16);self.server.poll(0)
        self.assertEqual(len(self.keeper._pins),0)
    def test_recovery_refuses_active_endpoint(self):
        self.start_process();ident=self.ipc.socket_identity(self.socket_path)
        self.err('ENDPOINT_BUSY',lambda:self.ipc.recover_stale(self.socket_path,ident));self.assertFalse(self.client.status(self.lid)['product_qualified'])
    def test_wrong_stale_identity_never_deletes(self):
        self.start_process();ident=self.ipc.socket_identity(self.socket_path);self.stop_process(kill=True)
        self.err('SOCKET_IDENTITY',lambda:self.ipc.recover_stale(self.socket_path,(ident[0],ident[1]+1)));self.assertTrue(self.socket_path.exists())
    def test_stale_socket_requires_explicit_recovery(self):
        self.start_process();ident=self.ipc.socket_identity(self.socket_path);self.stop_process(kill=True)
        self.open_keeper();self.err('SOCKET_EXISTS',lambda:self.ipc.Server(self.keeper,self.socket_path));self.keeper.close();self.keeper=None
        self.ipc.recover_stale(self.socket_path,ident);self.start_process(existing=True);self.assertFalse(self.client.status(self.lid)['product_qualified'])
    def test_shutdown_does_not_unlink_substituted_endpoint(self):
        self.start_local();self.socket_path.unlink();self.socket_path.write_bytes(b'not yours');self.server.close()
        self.assertEqual(self.socket_path.read_bytes(),b'not yours')
    def test_same_owner_second_server_cannot_steal(self):
        self.start_local();self.err('ENDPOINT_BUSY',lambda:self.ipc.Server(self.keeper,self.socket_path));self.assertTrue(self.socket_path.exists())
    def test_clock_deadline_bad_values(self):
        self.lid,_=self.ready()
        for value in (0,True,30001,1.5):self.err('PROTOCOL_SCHEMA',lambda value=value:self.ipc.Server(self.keeper,self.socket_path,deadline_ms=value))
    def test_connection_limit_bad_values(self):
        self.lid,_=self.ready()
        for value in (0,True,33):self.err('PROTOCOL_SCHEMA',lambda value=value:self.ipc.Server(self.keeper,self.socket_path,max_connections=value))
    def test_backend_failure_is_sanitized(self):
        self.start_local();c,hello=self.connect_local();q=self.request_raw(hello,'status');c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST))
        with patch.object(self.keeper,'status',side_effect=RuntimeError('/secret/input')):self.pump()
        r=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1);self.assertNotIn(b'/secret/input',r)
        self.err('REMOTE_INTERNAL',lambda:self.ipc.check_response(self.p,self.kp,hello,q,r))
    def test_request_noncanonical_cbor_refused(self):
        self.start_local();c,hello=self.connect_local();q=b'\x18\x01';c.sendall(self.ipc.frame(q,self.ipc.MAX_REQUEST));self.pump()
        r=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.ipc.check_response(self.p,self.kp,hello,q,r))
    def crash(self,phase):
        self.start_process();ident=self.ipc.socket_identity(self.socket_path);c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            c.connect(str(self.socket_path));hello=self.ipc.receive(c,self.ipc.MAX_HELLO,time.monotonic()+2);q=self.request_raw(hello,'status');packet=self.ipc.frame(q,self.ipc.MAX_REQUEST)
            if phase=='header':c.sendall(packet[:2])
            elif phase=='body':c.sendall(packet[:-1])
            elif phase=='submitted':c.sendall(packet)
            elif phase=='response':
                c.sendall(packet);c.settimeout(2);self.assertEqual(len(c.recv(1)),1)
            elif phase=='received':
                c.sendall(packet);r=self.ipc.receive(c,self.ipc.MAX_RESPONSE,time.monotonic()+2);self.ipc.check_response(self.p,self.kp,hello,q,r)
            rc,_,err=self.stop_process(kill=True);self.assertEqual(rc,-signal.SIGKILL)
            self.ipc.recover_stale(self.socket_path,ident);self.start_process(existing=True)
            self.assertFalse(self.client.status(self.lid)['product_qualified'])
            oid=sorted(self.bundle.objects)[0];self.assertEqual(self.client.fetch(self.lid,oid),self.bundle.objects[oid])
            self.assertEqual(err,'')
        finally:c.close()

def install(phase):
    def test(self):self.crash(phase)
    test.__name__='test_sigkill_server_'+phase;setattr(ServiceFaults,test.__name__,test)
for phase in ('hello','header','body','submitted','response','received'):install(phase)
