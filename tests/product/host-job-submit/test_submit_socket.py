import importlib,socket,threading,time
from submit_support import SubmitTest,h
from par_keeper_service.transport import receive,send
class SubmitSocket(SubmitTest):
    def setUp(self):
        super().setUp();self.server=None
        try:self.net=importlib.import_module('par_job_submit.server');self.cl=importlib.import_module('par_job_submit.client')
        except ModuleNotFoundError:self.net=None
        self.assertIsNotNone(self.net,'submission endpoint is not implemented')
        self.spath=self.socket_dir/'submit.sock';self.server=self.net.Server(self.st,self.spath,deadline_ms=500)
    def tearDown(self):
        if getattr(self,'server',None):self.server.close()
        super().tearDown()
    def connect_submit(self):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(1);s.connect(str(self.spath));self.sockets.append(s)
        self.server.poll(0);self.server.poll(0);return s,receive(s,self.sc.MAX_HELLO,time.monotonic()+1)
    def exchange(self,action,desc=None,offset=None,data=None):
        s,hi=self.connect_submit();req=self.sc.make_request(self.p,self.os,hi,action,desc,offset,data);send(s,req,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(6):self.server.poll(0)
        raw=receive(s,self.sc.MAX_RESPONSE,time.monotonic()+1)
        return self.sc.check_response(self.p,self.kp,hi,req,raw)
    def test_context(self):self.assertEqual(self.exchange('context')['target_digest'],self.st.target().hex())
    def test_real_staged_submit(self):
        r=self.payload();d=self.descriptor(r);self.exchange('begin',d);self.exchange('chunk',d,0,r);v=self.exchange('submit',d)
        self.assertEqual(v['state'],'REGISTERED');self.assertIsNone(self.host.selected)
    def test_control_data_limits_unchanged(self):
        from par_job_control import protocol as old
        self.assertEqual(old.MAX_REQUEST,16384);self.assertEqual(self.sc.MAX_REQUEST,65536)
    def test_request_size_bound(self):
        s,_=self.connect_submit();s.sendall((self.sc.MAX_REQUEST+1).to_bytes(4,'big'));self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_zero_frame(self):
        s,_=self.connect_submit();s.sendall(bytes(4));self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_old_connection_cannot_replay_request(self):
        s,h1=self.connect_submit();req=self.sc.make_request(self.p,self.os,h1,'context');s2,h2=self.connect_submit();send(s2,req,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(5):self.server.poll(0)
        raw=receive(s2,self.sc.MAX_RESPONSE,time.monotonic()+1);self.err(None,lambda:self.sc.check_response(self.p,self.kp,h2,req,raw))
    def test_wrong_operator_request(self):
        s,hi=self.connect_submit();body={0:1,1:self.sc.PROFILE,2:self.sc.sha(hi),3:'context',4:None,5:None,6:None}
        req=self.sc.signed(self.p,h('wrong'),'request',body,self.sc.MAX_REQUEST);send(s,req,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(5):self.server.poll(0)
        raw=receive(s,self.sc.MAX_RESPONSE,time.monotonic()+1);self.err(None,lambda:self.sc.check_response(self.p,self.kp,hi,req,raw));self.assertEqual(self.host.jobs.list(),[])
    def test_request_no_generic_method(self):
        s,hi=self.connect_submit();self.err(None,lambda:self.sc.make_request(self.p,self.os,hi,'eval'))
    def test_revoked_connection_drops_response(self):
        s,hi=self.connect_submit();req=self.sc.make_request(self.p,self.os,hi,'context');self.ctl.replace_controller(None,2);send(s,req,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(5):self.server.poll(0)
        self.assertEqual(len(self.server.connections),0)
    def test_deadline(self):
        s,_=self.connect_submit();time.sleep(.55);self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_submit_socket_not_data_activity(self):
        s,_=self.connect_submit();self.assertEqual(self.host.activity.snapshot()['connections'],0)
    def test_data_activity_still_counted(self):
        s,_=self.connect_submit();d,_=self.connect();self.assertEqual(self.host.activity.snapshot()['connections'],1)
    def test_duplicate_after_lost_response(self):
        d,r=self.ready();s,hi=self.connect_submit();req=self.sc.make_request(self.p,self.os,hi,'submit',d);send(s,req,self.sc.MAX_REQUEST,time.monotonic()+1)
        for _ in range(4):self.server.poll(0)
        s.close();self.assertEqual(self.exchange('submit',d)['state'],'REGISTERED');self.assertEqual(len(self.host.jobs.list()),1)
    def test_capacity(self):
        self.server.close();self.server=self.net.Server(self.st,self.spath,max_connections=1)
        s,_=self.connect_submit();other=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);other.connect(str(self.spath));self.sockets.append(other);self.server.poll(0)
        self.assertEqual(len(self.server.connections),1);self.assertGreater(self.server.counts['overload'],0)
    def test_client_real_exchange(self):
        out=[]
        def client():
            try:out.append(self.cl.Client(self.spath,self.p,self.kp,self.store_id,self.os,1).call('context'))
            except Exception as e:out.append(e)
        t=threading.Thread(target=client);t.start()
        for _ in range(200):
            self.server.poll(.001)
            if not t.is_alive():break
        t.join(1);self.assertFalse(t.is_alive());self.assertIsInstance(out[0],dict)
    def test_response_context_not_stage(self):
        d=self.descriptor();s,hi=self.connect_submit();req=self.sc.make_request(self.p,self.os,hi,'begin',d)
        raw=self.sc.make_response(self.p,self.ks,hi,req,True,self.st.context());self.err('SUBMIT_RESPONSE',lambda:self.sc.check_response(self.p,self.kp,hi,req,raw))
    def test_context_revision_must_match_hello(self):
        s,hi=self.connect_submit();req=self.sc.make_request(self.p,self.os,hi,'context');v=self.st.context();v['controller_revision']=2
        raw=self.sc.make_response(self.p,self.ks,hi,req,True,v);self.err('SUBMIT_RESPONSE',lambda:self.sc.check_response(self.p,self.kp,hi,req,raw))
    def test_client_rejects_nonadvancing_ack(self):
        from unittest.mock import patch
        r=self.payload();d=self.descriptor(r);v=self.st.begin(d);cli=self.cl.Client(self.spath,self.p,self.kp,self.store_id,self.os,1)
        # Simulate a correctly-shaped but nonadvancing remote ack; no unbounded loop.
        with patch.object(cli,'call',side_effect=[v,v,RuntimeError('loop continued')]):self.err('SUBMIT_PROGRESS',lambda:cli.stage(r,d))
    def test_client_rejects_jump_ack(self):
        from unittest.mock import patch
        r=self.sc.pack_job('close',b'cmd',b'a'*70000);d=self.descriptor(r);v=self.st.begin(d);bad=dict(v,received=len(r),prefix_hash=self.sc.sha(r).hex(),state='READY')
        cli=self.cl.Client(self.spath,self.p,self.kp,self.store_id,self.os,1)
        with patch.object(cli,'call',side_effect=[v,bad]):self.err('SUBMIT_PROGRESS',lambda:cli.stage(r,d))
