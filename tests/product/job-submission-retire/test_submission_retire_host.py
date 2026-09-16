import importlib,socket,time
from pathlib import Path
from submission_retire_support import RetireTest,h
from par_keeper_service.transport import receive,send
class RetirementHostTests(RetireTest):
    def setUp(self):
        super().setUp();self.whole=None
        try:self.hm=importlib.import_module('par_submit_retire.host')
        except ModuleNotFoundError:self.hm=None
        self.assertIsNotNone(self.hm,'compatible retirement submission host not implemented')
        self.st.close();self.ctl.close();self.host.close();self.st=None;self.ctl=None;self.host=None
        self.cpath=self.socket_dir/'control.sock';self.spath=self.socket_dir/'submit.sock';self.open_host()
    def open_host(self):
        self.whole=self.hm.RetiringSubmissionHost(self.keeper,self.window,self.socket_path,self.upload_path,self.cpath,self.spath,self.jroot,Path(self.tmp.name)/'controller',self.sroot,self.op,1,submit_deadline_ms=500)
        self.host=self.whole.scheduler;self.ctl=self.whole.controller;self.st=self.whole.submissions
    def tearDown(self):
        if self.whole:self.whole.close();self.whole=None;self.host=None;self.ctl=None;self.st=None
        super().tearDown()
    def exchange(self,method,descriptor=None,offset=None,data=None):
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(2);self.sockets.append(sock);sock.connect(str(self.spath))
        self.whole.tick(0);self.whole.tick(0);hi=receive(sock,self.sc.MAX_HELLO,time.monotonic()+2)
        req=self.sc.make_request(self.p,self.os,hi,method,descriptor,offset,data);send(sock,req,self.sc.MAX_REQUEST,time.monotonic()+2)
        for _ in range(5):self.whole.tick(0)
        return self.sc.check_response(self.p,self.kp,hi,req,receive(sock,self.sc.MAX_RESPONSE,time.monotonic()+2))
    def test_registration_after_retirement_on_same_socket(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));d2=self.descriptor(r,h('second-job'))
        self.assertEqual(self.exchange('begin',d2)['state'],'RECEIVING');self.exchange('chunk',d2,0,r)
        self.assertEqual(self.exchange('submit',d2)['state'],'REGISTERED');self.assertIsNone(self.host.selected)
    def test_retired_descriptor_refused_over_socket(self):
        d,r=self.partial();self.st.retire(self.retire_request(d))
        for method in ('begin','progress','submit','reconcile','retry'):self.err('REMOTE_REJECTED',lambda m=method:self.exchange(m,d))
    def test_in_progress_connection_cannot_resurrect(self):
        d,r=self.partial();sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(2);self.sockets.append(sock);sock.connect(str(self.spath))
        self.whole.tick(0);self.whole.tick(0);hi=receive(sock,self.sc.MAX_HELLO,time.monotonic()+2)
        req=self.sc.make_request(self.p,self.os,hi,'chunk',d,17,r[17:]);self.st.retire(self.retire_request(d));send(sock,req,self.sc.MAX_REQUEST,time.monotonic()+2)
        for _ in range(5):self.whole.tick(0)
        raw=receive(sock,self.sc.MAX_RESPONSE,time.monotonic()+2);self.err('REMOTE_REJECTED',lambda:self.sc.check_response(self.p,self.kp,hi,req,raw))
    def test_new_delete_method_not_exposed(self):
        self.assertNotIn('retire',self.sc.METHODS);self.assertNotIn('rebind',self.sc.METHODS)
    def test_registered_job_can_be_selected_after_payload_retirement(self):
        d,r=self.ready();self.exchange('submit',d);self.st.retire(self.retire_request(d));self.host.schedule(self.jid())
        for _ in range(10):self.whole.tick(0)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
    def test_restart_preserves_refusal(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));self.whole.close();self.open_host();self.err('REMOTE_REJECTED',lambda:self.exchange('begin',d))
    def test_data_socket_activity_unchanged(self):
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.connect(str(self.socket_path));self.sockets.append(sock)
        self.whole.tick(0);self.whole.tick(0);self.assertEqual(self.host.activity.snapshot()['connections'],1)
    def test_context_is_still_registration_only(self):
        self.assertEqual(self.exchange('context')['target_digest'],self.st.target().hex());self.assertEqual(self.whole.diagnostics()['submission_scope'],'REGISTRATION_ONLY')
