"""Additional review probes: malformed status and response-loss semantics."""
import os,socket,threading,time
from service_support import ServiceTest,h
from par_keeper_service.server import status_unpack

class ServiceHardening(ServiceTest):
    def test_incomplete_status_is_not_a_valid_success(self):
        self.err('RESPONSE_TYPE',lambda:status_unpack([['state','RETAINED_ACTIVE'],['recipient_validated',False],['product_qualified',False]]))
    def test_unknown_status_is_rejected(self):
        self.start_local();v=self.status(self.lid);v['state']='MAGIC_PERMANENT_SAFETY'
        self.err('RESPONSE_TYPE',lambda:status_unpack([[k,x] for k,x in sorted(v.items())]))
    def test_duplicate_status_field_rejected(self):
        self.start_local();v=self.status(self.lid);pairs=[[k,x] for k,x in sorted(v.items())];pairs.append(['state',v['state']])
        self.err('RESPONSE_TYPE',lambda:status_unpack(pairs))
    def test_status_cannot_claim_product_qualification(self):
        self.start_local();v=self.status(self.lid);v['product_qualified']=True
        self.err('RESPONSE_TYPE',lambda:status_unpack([[k,x] for k,x in sorted(v.items())]))
    def test_status_cannot_claim_network_reachability(self):
        self.start_local();v=self.status(self.lid);v['currently_network_reachable']=True
        self.err('RESPONSE_TYPE',lambda:status_unpack([[k,x] for k,x in sorted(v.items())]))
    def test_status_integer_is_not_boolean(self):
        self.start_local();v=self.status(self.lid);v['received']=True
        self.err('RESPONSE_TYPE',lambda:status_unpack([[k,x] for k,x in sorted(v.items())]))
    def test_response_loss_is_unknown_without_auto_retry(self):
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(str(self.socket_path));os.chmod(self.socket_path,0o600);listener.listen(2);listener.settimeout(1)
        seen=[];errors=[]
        def backend():
            try:
                c,_=listener.accept()
                with c:
                    hello=self.ipc.make_hello(self.p,self.ks,h('fakeboot'),h('fresh'),1000)
                    self.ipc.send(c,hello,self.ipc.MAX_HELLO,time.monotonic()+1)
                    raw=self.ipc.receive(c,self.ipc.MAX_REQUEST,time.monotonic()+1);self.ipc.check_request(self.p,self.kp,hello,raw);seen.append(raw)
                    c.sendall(b'\x00\x00\x00\x40truncated')
                listener.settimeout(.1)
                try:
                    c,_=listener.accept();c.close();errors.append('automatic retry')
                except socket.timeout:pass
            except Exception as e:errors.append(repr(e))
        t=threading.Thread(target=backend);t.start()
        try:
            client=self.ipc.Client(self.socket_path,self.p,self.kp,self.cs,self.cap,timeout=1)
            self.err('OUTCOME_UNKNOWN',lambda:client.status(h('lease')))
        finally:t.join(3);listener.close()
        self.assertFalse(t.is_alive());self.assertEqual(errors,[]);self.assertEqual(len(seen),1)
    def test_stale_lockfile_hardlink_refused(self):
        other=self.socket_dir/'other';other.write_bytes(b'');other.chmod(0o600);lock=self.socket_path.with_name(self.socket_path.name+'.lock');os.link(other,lock)
        self.lid,_=self.ready();self.err('SOCKET_PERMISSIONS',lambda:self.ipc.Server(self.keeper,self.socket_path))
    def test_stale_lockfile_symlink_refused(self):
        other=self.socket_dir/'other';other.write_bytes(b'keep');lock=self.socket_path.with_name(self.socket_path.name+'.lock');lock.symlink_to(other)
        self.lid,_=self.ready()
        with self.assertRaises(Exception):self.ipc.Server(self.keeper,self.socket_path)
        self.assertEqual(other.read_bytes(),b'keep')
