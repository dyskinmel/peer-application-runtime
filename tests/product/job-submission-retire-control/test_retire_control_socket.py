import socket,time
from unittest.mock import patch
from retire_control_support import SocketTest,h
from par_keeper_service.transport import receive,send
class SocketTests(SocketTest):
    def test_legacy_registration_unchanged(self):
        d,r=self.partial();self.assertEqual(self.exchange('progress',d,legacy=True)['received'],17)
        self.exchange('chunk',d,legacy=True,offset=17,data=r[17:]);v=self.exchange('submit',d,legacy=True)
        self.assertEqual(v['state'],'REGISTERED');self.assertIsNone(self.host.selected)
    def test_proposal_then_retirement_and_status(self):
        d,_=self.partial();prop=self.exchange('proposal',d)['proposal']
        auth=self.rc.make_request(self.p,self.os,self.os,revision=1,nonce=h('wire-retire'),**prop)
        v=self.exchange('retire',d,auth);self.assertEqual(v['retirement']['state'],'TOMBSTONED')
        self.assertEqual(v,self.exchange('status',d));self.assertIsNone(self.host.selected)
    def test_status_before_retirement(self):
        d,_=self.partial();v=self.exchange('status',d)
        self.assertIsNone(v['retirement']);self.assertEqual(v['stage_state'],'RECEIVING')
    def test_replay_idempotent_and_legacy_rejected(self):
        d,_=self.partial();q=self.retire_request(d);v=self.exchange('retire',d,q)
        self.assertEqual(self.exchange('retire',d,q),v)
        self.err('REMOTE_REJECTED',lambda:self.exchange('begin',d,legacy=True))
    def test_registered_job_kept_and_selectable(self):
        d,_=self.ready();self.exchange('submit',d,legacy=True);before=self.host.jobs.journal.path(self.jid()).read_bytes()
        self.exchange('retire',d,self.retire_request(d))
        self.assertEqual(self.host.jobs.journal.path(self.jid()).read_bytes(),before)
        self.host.schedule(self.jid())
        for _ in range(12):self.whole.tick(0)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
    def test_stale_target_refused_without_deletion(self):
        d,r=self.partial();q=self.retire_request(d);self.st.chunk(d,17,r[17:])
        self.err('REMOTE_REJECTED',lambda:self.exchange('retire',d,q));self.assertTrue(self.st.payload_path(self.jid()).exists())
    def test_other_descriptor_cannot_be_probed(self):
        d,_=self.partial();self.err('REMOTE_REJECTED',lambda:self.exchange('proposal',self.descriptor(jid=h('unknown'))))
    def test_connection_is_not_counted_as_data_transfer(self):
        s,hi=self.connect();self.assertEqual(self.host.activity.snapshot()['connections'],0)
        self.assertEqual(self.whole.submit_server.diagnostics()['active_connections'],1)
    def test_data_connection_still_counted(self):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path));self.sockets.append(s)
        self.whole.tick(0);self.whole.tick(0);self.assertEqual(self.host.activity.snapshot()['connections'],1)
    def test_old_connection_after_rotation_rejected(self):
        d,_=self.partial();sock,hi=self.connect();raw=self.ext_request('status',d,hello=hi)
        self.ctl.replace_controller(self.p.sign_public(h('new')),2);send(sock,raw,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(8):self.whole.tick(0)
        self.err(None,lambda:receive(sock,self.sc.MAX_RESPONSE,time.monotonic()+1))
    def test_new_controller_can_rebind_same_target(self):
        d,_=self.partial();q=self.retire_request(d)
        def stop(name):
            if name=='submit.retire.before_unlink':raise RuntimeError('test stop before unlink')
        self.st.observer=stop
        with self.assertRaises(RuntimeError):self.st.retire(q)
        self.st.observer=None
        ns=h('next');self.ctl.replace_controller(self.p.sign_public(ns),2)
        prop=self.exchange('proposal',d,seed=ns)['proposal'];q2=self.rc.make_request(self.p,ns,self.os,revision=2,nonce=h('new-q'),**prop)
        self.assertEqual(self.exchange('rebind',d,q2,seed=ns)['retirement']['state'],'INTENT')
        self.assertTrue(self.st.payload_path(self.jid()).exists())
        self.assertEqual(self.exchange('retire',d,q2,seed=ns)['retirement']['state'],'TOMBSTONED')
    def test_inflight_reconcile_does_not_register(self):
        d,_=self.ready();self.stop_at('submit.before_dispatch',lambda:self.st.submit(d))
        # The exact observer boundary is asserted by the existing state.
        m,_=self.st._read(self.jid());self.assertEqual(m[7],'INFLIGHT')
        q=self.retire_request(d);v=self.exchange('reconcile_registration',d,q)
        self.assertEqual(v['stage_state'],'RETRY_READY');self.assertFalse(self.host.jobs.journal.path(self.jid()).exists())
    def test_no_fifth_socket(self):
        self.assertEqual(len(list(self.socket_dir.glob('*.sock'))),4)
    def test_mutation_error_after_dispatch_is_uncertain(self):
        d,_=self.partial();q=self.retire_request(d)
        def changed_then_fail(raw):
            original(raw);raise RuntimeError('after effect')
        original=self.st.retire
        with patch.object(self.st,'retire',changed_then_fail):
            self.err('REMOTE_UNCERTAIN',lambda:self.exchange('retire',d,q))
        self.assertEqual(self.exchange('status',d)['retirement']['state'],'TOMBSTONED')
    def test_status_shape_no_success_conflation(self):
        d,_=self.partial();q=self.retire_request(d);v=self.exchange('retire',d,q)
        for k in ('job_cancelled','records_reclaimed','secure_erase','physical_disk_quota','product_qualified'):
            self.assertIs(v['retirement'][k],False)
    def test_unsupported_profile_does_not_kill_server(self):
        s,hi=self.connect();send(s,b'not-cbor',65536,time.monotonic()+1)
        for _ in range(6):self.whole.tick(0)
        d,_=self.partial();self.assertEqual(self.exchange('status',d)['kind'],'status')

    def test_post_effect_view_failure_is_uncertain(self):
        d,_=self.partial();q=self.retire_request(d);control=self.whole.submit_server.retirement
        original=control._view;calls=[]
        def fail_second(*args,**kw):
            calls.append(1)
            if len(calls)>1:raise self.sc.E('RETIRE_CONTROL_VIEW')
            return original(*args,**kw)
        with patch.object(control,'_view',side_effect=fail_second):
            self.err('REMOTE_UNCERTAIN',lambda:self.exchange('retire',d,q))
        self.assertEqual(self.exchange('status',d)['retirement']['state'],'TOMBSTONED')
    def test_old_registration_connection_cannot_resurrect_after_retirement(self):
        d,r=self.partial();sock,hi=self.connect()
        old=self.sc.make_request(self.p,self.os,hi,'chunk',d,17,r[17:])
        self.exchange('retire',d,self.retire_request(d))
        send(sock,old,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(8):self.whole.tick(0)
        reply=receive(sock,self.sc.MAX_RESPONSE,time.monotonic()+1)
        self.err('REMOTE_REJECTED',lambda:self.sc.check_response(self.p,self.kp,hi,old,reply))
    def test_capacity_limit_rejects_extra_connection_not_other_clients(self):
        socks=[self.connect()[0] for _ in range(4)]
        extra=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sockets.append(extra);extra.connect(str(self.spath))
        self.whole.tick(0);self.whole.tick(0)
        self.err(None,lambda:receive(extra,4096,time.monotonic()+1))
        for sock in socks:sock.close()
        for _ in range(4):self.whole.tick(0)
        d,_=self.partial();self.assertEqual(self.exchange('status',d)['stage_state'],'RECEIVING')
    def test_oversize_request_is_closed_without_mutation(self):
        d,_=self.partial();sock,hi=self.connect();sock.sendall((65537).to_bytes(4,'big'))
        for _ in range(4):self.whole.tick(0)
        self.err(None,lambda:receive(sock,16384,time.monotonic()+1))
        self.assertTrue(self.st.payload_path(self.jid()).exists())
    def test_partial_request_uses_absolute_deadline(self):
        sock,hi=self.connect();sock.sendall((200).to_bytes(4,'big')+b'x')
        time.sleep(.55)
        self.whole.tick(0)
        self.assertEqual(self.whole.submit_server.diagnostics()['active_connections'],0)
