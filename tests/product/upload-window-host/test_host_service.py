import importlib,socket,time
from host_support import HostTest,h,pr
from par_keeper_service.transport import receive,send,frame
class WindowService(HostTest):
    def setUp(self):
        super().setUp()
        try:self.mod=importlib.import_module('par_window_host.server')
        except ModuleNotFoundError:self.mod=None
        self.assertIsNotNone(self.mod,'window server is not implemented')
    def start_listener(self,**kw):self.server=self.mod.Server(self.keeper,self.window,self.upload_path,**kw)
    def connect(self):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.upload_path));s.settimeout(1);self.c=s
        self.pump(2);return s,receive(s,4096,time.monotonic()+1)
    def rpc(self,q):
        s,hello=self.connect();raw=self.host_request(hello,q);send(s,raw,65536,time.monotonic()+1);self.pump(8)
        return self.hp.check_response(self.p,self.kp,hello,raw,receive(s,1048576,time.monotonic()+1))
    def test_begin_uses_gateway_and_binding(self):
        self.start_listener();q=self.command();token=self.rpc(q)[0];self.assertTrue((self.wroot/'bindings'/(token.hex()+'.bound')).is_file())
    def test_raw_legacy_command_no_side_effect(self):
        self.start_listener();s,hello=self.connect();raw=self.cmd('progress',h('x'));send(s,raw,65536,time.monotonic()+1);self.pump()
        self.assertEqual(self.window.diagnostics()['records'],0)
    def test_delayed_old_request_after_close(self):
        self.start_listener();s,hello=self.connect();q=self.command();req=self.host_request(hello,q);self.finish()
        send(s,req,65536,time.monotonic()+1);self.pump()
        self.err('REMOTE_STALE_WINDOW',lambda:self.hp.check_response(self.p,self.kp,hello,req,receive(s,1048576,time.monotonic()+1)))
        self.assertEqual(self.window.diagnostics()['records'],0)
    def test_delayed_old_request_after_next_generation(self):
        self.start_listener();s,hello=self.connect();q=self.command();req=self.host_request(hello,q);self.next_window()
        send(s,req,65536,time.monotonic()+1);self.pump()
        self.err('REMOTE_STALE_WINDOW',lambda:self.hp.check_response(self.p,self.kp,hello,req,receive(s,1048576,time.monotonic()+1)))
        self.assertEqual(self.window.diagnostics()['records'],0)
    def test_response_dropped_after_local_close(self):
        self.terminal();q=self.wrap(self.cmd('progress',pr.token_for(self.p,self.beginraw)))
        # A retired stage must not be made writable by the host, so use an empty window seal-free terminal index.
        receipt=self.finish();self.next_window(receipt);self.complete_index();q=self.wrap(self.cmd('progress',pr.token_for(self.p,self.beginraw)))
        self.start_listener(send_chunk=1);s,hello=self.connect();req=self.host_request(hello,q);send(s,req,65536,time.monotonic()+1)
        self.server.poll(.02);self.server.poll(.02);self.finish();self.pump()
        self.assertGreaterEqual(self.server.diagnostics()['authority_changed'],1)
    def test_management_wrapper_rejected_even_valid_outer_signature(self):
        self.upload_stage(1);q=self.wrap(self.retirement_request(),'retire');self.start_listener();s,hello=self.connect()
        req=self.hp._signed(self.p,self.cs,'request',{0:1,1:self.hp.PROFILE,2:self.hp.digest(hello),3:q},65536)
        send(s,req,65536,time.monotonic()+1);self.pump()
        self.err('REMOTE_REJECTED',lambda:self.hp.check_response(self.p,self.kp,hello,req,receive(s,1048576,time.monotonic()+1)))
        self.assertFalse(self.live(pr.token_for(self.p,self.beginraw),'.retirement').exists())
    def test_current_authority_checked_after_handshake(self):
        self.start_listener();s,hello=self.connect();q=self.command();req=self.host_request(hello,q);self.change_authority()
        send(s,req,65536,time.monotonic()+1);self.pump()
        self.err(None,lambda:self.hp.check_response(self.p,self.kp,hello,req,receive(s,1048576,time.monotonic()+1)))
        self.assertEqual(self.window.diagnostics()['records'],0)
    def test_overlarge_frame_rejected_before_allocation(self):
        self.start_listener();s,hello=self.connect();s.sendall((65537).to_bytes(4,'big'));self.pump();self.assertEqual(s.recv(1),b'')
    def test_unknown_method_request_no_mutation(self):
        self.start_listener();s,hello=self.connect();req=self.hp._signed(self.p,self.cs,'request',{0:1,1:self.hp.PROFILE,2:self.hp.digest(hello),3:b'gc'},65536)
        send(s,req,65536,time.monotonic()+1);self.pump();self.assertEqual(self.window.diagnostics()['records'],0)
    def test_one_request_per_connection(self):
        self.start_listener();q=self.command();self.assertEqual(self.rpc(q)[1],0);self.assertEqual(self.c.recv(1),b'')
    def test_idle_deadline_closes_connection(self):
        self.start_listener(deadline_ms=50);s,hello=self.connect();time.sleep(.07);self.pump(2);self.assertEqual(s.recv(1),b'')
    def test_legacy_spool_is_not_a_gateway(self):
        self.err('GATEWAY_REQUIRED',lambda:self.mod.Server(self.keeper,self.window._inner,self.upload_path))
    def test_phase_is_sent_but_not_auto_advanced(self):
        self.finish();self.start_listener();s,hello=self.connect();b=self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,hello);self.assertEqual(b[11],'CLEANED');self.assertEqual(self.window.phase,'CLEANED')
    def test_half_request_never_reaches_admission(self):
        self.start_listener();s,hello=self.connect();raw=frame(self.host_request(hello),65536);s.sendall(raw[:-1]);self.pump(3);self.assertEqual(self.window.diagnostics()['records'],0)
