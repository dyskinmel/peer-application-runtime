"""Real Unix sockets in a private temp directory; no network targets."""
import importlib,socket,threading,time
from control_support import ControlTest,h
from par_keeper_service.transport import receive,send
class ControlSocket(ControlTest):
    def setUp(self):
        super().setUp()
        try:self.net=importlib.import_module('par_job_control.server');self.clientmod=importlib.import_module('par_job_control.client')
        except ModuleNotFoundError:self.net=None
        self.assertIsNotNone(self.net,'control socket not implemented')
        self.control_path=self.socket_dir/'control.sock';self.server=self.net.Server(self.ctl,self.control_path,deadline_ms=500)
    def tearDown(self):
        if getattr(self,'server',None):self.server.close()
        super().tearDown()
    def connect_control(self):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(1);s.connect(str(self.control_path));self.sockets.append(s)
        self.server.poll(0);self.server.poll(0);return s,receive(s,self.pr.MAX_HELLO,time.monotonic()+1)
    def control_request(self,action='status',*,opid=None,jid='default'):
        s,hello=self.connect_control();i=self.intent(action,opid,jid)
        raw=self.pr.make_request(self.p,self.os,hello,i);send(s,raw,self.pr.MAX_REQUEST,time.monotonic()+1)
        for _ in range(5):self.server.poll(0)
        resp=receive(s,self.pr.MAX_RESPONSE,time.monotonic()+1)
        return self.pr.check_response(self.p,self.kp,hello,raw,resp)
    def test_real_status(self):self.assertEqual(self.control_request()['job']['state'],'QUEUED')
    def test_real_select_and_cancel(self):
        self.assertEqual(self.control_request('select')['host']['mode'],'DRAINING');self.assertEqual(self.control_request('cancel')['job']['state'],'CANCELLED')
    def test_control_not_counted_in_data_drain(self):
        s,hello=self.connect_control();self.assertEqual(self.host.activity.snapshot()['connections'],0)
        self.control_request('select');self.complete();self.assertEqual(self.host.gateway.phase,'CLOSED')
    def test_data_count_not_hidden_by_control(self):
        s,hello=self.connect();self.control_request('select');self.tick(4)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED');self.assertEqual(self.host.activity.snapshot()['connections'],1)
        self.control_request('cancel');self.assertEqual(self.host.gateway.phase,'OPEN')
    def test_control_during_drain(self):
        s,_=self.connect(upload=True);self.control_request('select');r=self.control_request();self.assertEqual(r['host']['connections'],1);self.assertFalse(r['host']['upload_accepting'])
    def test_wrong_key_no_job_effect(self):
        s,hello=self.connect_control();raw=self.intent(seed=h('wrong'))
        # Forge only the wrapper with the wrong key; receiver must refuse.
        req=self.pr._sign(self.p,h('wrong'),'request',{0:1,1:self.pr.PROFILE,2:self.pr.digest(hello),3:raw},self.pr.MAX_REQUEST)
        send(s,req,self.pr.MAX_REQUEST,time.monotonic()+1)
        for _ in range(4):self.server.poll(0)
        self.assertIsNone(self.host.selected);self.assertEqual(list(self.cr.glob('*.op')),[])
    def test_old_connection_after_revocation(self):
        s,hello=self.connect_control();req=self.pr.make_request(self.p,self.os,hello,self.intent())
        self.ctl.replace_controller(None,2);send(s,req,self.pr.MAX_REQUEST,time.monotonic()+1)
        for _ in range(4):self.server.poll(0)
        self.assertIsNone(self.host.selected)
    def test_oversized_length_dropped(self):
        s,_=self.connect_control();s.sendall((self.pr.MAX_REQUEST+1).to_bytes(4,'big'));self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_zero_length_dropped(self):
        s,_=self.connect_control();s.sendall(bytes(4));self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_slow_control_does_not_block_data(self):
        s,_=self.connect_control();d,_=self.connect();self.assertEqual(self.host.activity.snapshot()['connections'],1)
    def test_fixed_deadline_expires(self):
        s,_=self.connect_control();time.sleep(.55);self.server.poll(0);self.assertEqual(len(self.server.connections),0)
    def test_socket_permissions(self):
        import stat
        self.assertEqual(stat.S_IMODE(self.control_path.stat().st_mode),0o600)
    def test_connection_limit(self):
        self.server.close();self.server=self.net.Server(self.ctl,self.control_path,max_connections=1,deadline_ms=500)
        s,_=self.connect_control();other=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);other.connect(str(self.control_path));self.sockets.append(other);self.server.poll(0)
        self.assertEqual(len(self.server.connections),1);self.assertGreater(self.server.counts['overload'],0)
    def test_response_lost_retry_same_intent(self):
        s,hello=self.connect_control();raw=self.pr.make_request(self.p,self.os,hello,self.intent('cancel'));send(s,raw,self.pr.MAX_REQUEST,time.monotonic()+1)
        for _ in range(3):self.server.poll(0)
        s.close();r=self.control_request('cancel');self.assertTrue(r['duplicate']);self.assertEqual(r['job']['state'],'CANCELLED')
    def test_client_pinned_exchange(self):
        result=[]
        def client():
            try:result.append(self.clientmod.Client(self.control_path,self.p,self.kp,self.store_id,self.os,1).call('status',self.jid()))
            except Exception as ex:result.append(ex)
        t=threading.Thread(target=client);t.start()
        for _ in range(100):
            self.server.poll(.001)
            if not t.is_alive():break
        t.join(1);self.assertFalse(t.is_alive());self.assertIsInstance(result[0],dict);self.assertEqual(result[0]['outcome'],'STATUS')
    def test_mutation_requires_explicit_operation_id(self):
        c=self.clientmod.Client(self.control_path,self.p,self.kp,self.store_id,self.os,1)
        self.err(None,lambda:c.call('select',self.jid()))
    def test_control_socket_alias_refused(self):
        self.err(None,lambda:self.net.Server(self.ctl,self.socket_path))
