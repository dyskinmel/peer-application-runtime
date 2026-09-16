import hashlib,importlib,json,os,select,signal,socket,subprocess,sys,time
from pathlib import Path
from dataclasses import replace
from upload_support import UploadTest,h,pr
from service_support import ROOT
import test_service_recovery as recovery_tests

class UploadService(UploadTest):
    job=recovery_tests.ServiceRecovery.job
    remote=recovery_tests.ServiceRecovery.remote
    remove_donor=recovery_tests.ServiceRecovery.remove_donor
    run_receiver=recovery_tests.ServiceRecovery.run_receiver
    def setUp(self):
        super().setUp()
        try:self.uc=importlib.import_module('par_keeper_upload.client')
        except ModuleNotFoundError:self.uc=None
        self.assertTrue(self.uc is not None,'Upload client not implemented')
        self.upload_path=self.socket_dir/'upload.sock'
    def start_upload_process(self):
        cfg=self.config()
        if self.spool is not None:self.spool.close();self.spool=None
        if self.keeper is not None:self.keeper.close();self.keeper=None
        args=[sys.executable,'-I','-S',str(ROOT/'tools/keeper_upload_host.py'),'--root',str(self.path),'--socket',str(self.socket_path),'--upload-socket',str(self.upload_path),'--host-config',str(cfg),'--key-fd','0','--deadline-ms','2000','--allow-unpatched-sqlite','--allow-legacy-sodium']
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,env={'PATH':os.environ.get('PATH','')})
        self.process.stdin.write(self.ks);self.process.stdin.close();self.process.stdin=None
        self.assertTrue(select.select([self.process.stdout],[],[],6)[0],'host startup deadline')
        line=self.process.stdout.readline();self.assertTrue(line,self.process.stderr.read().decode() if self.process.poll() is not None else 'no READY')
        self.assertEqual(json.loads(line)['state'],'READY')
        self.uclient=self.uc.Client(self.upload_path,self.p,self.kp,self.cs,self.cap,timeout=3)
        self.client=self.ipc.Client(self.socket_path,self.p,self.kp,self.cs,self.cap,timeout=3)
    def send_bundle(self,op=None):
        self.lid,rc=self.uclient.upload_bundle(self.bundle.index,self.rpin,self.bundle.objects,30,op or h('upload-root'))
        return self.lid,rc
    def test_donor_upload_then_read(self):
        self.start_upload_process();lid,rc=self.send_bundle()
        self.assertEqual(self.client.receipt(lid),rc)
        for oid,raw in self.bundle.objects.items():self.assertEqual(self.remote().fetch(oid),raw)
    def test_whole_upload_retry_no_lease_double_charge_or_extension(self):
        self.start_upload_process();lid,rc=self.send_bundle();lid2,rc2=self.send_bundle()
        self.assertEqual((lid,rc),(lid2,rc2));self.assertEqual(self.client.status(lid)['generation'],1)
    def test_separate_donor_and_recipient_processes(self):
        self.start_upload_process()
        job=Path(self.tmp.name)/'donor.json'
        job.write_text(json.dumps({'socket':str(self.upload_path),'keeper':self.kp.hex(),'seed':self.cs.hex(),'cap':self.cap.hex(),'index':self.bundle.index.hex(),'pin':pr.dump(__import__('par_keeper.contract',fromlist=['pin_values']).pin_values(self.rpin),65536).hex(),'objects':{k.hex():v.hex() for k,v in self.bundle.objects.items()}}));job.chmod(0o600)
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('donor_worker.py')),str(job)],capture_output=True,timeout=20,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,0,cp.stderr.decode());self.lid=bytes.fromhex(json.loads(cp.stdout)['lease'])
        job.unlink();expected=self.remove_donor();result=self.run_receiver(self.job())
        self.assertEqual(result['sha256'],expected);self.assertFalse(result['status']['writable'])
    def test_restart_after_partial_index(self):
        self.start_upload_process();token,state=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'))
        self.uclient.chunk(token,0,self.bundle.index[:24]);self.stop_process();self.start_upload_process()
        state=self.uclient.progress(token);self.assertEqual(state[1],24)
        self.uclient.chunk(token,24,self.bundle.index[24:]);self.assertEqual(self.uclient.progress(token)[1],len(self.bundle.index))
    def test_index_larger_than_request_is_chunked(self):
        # Real fixture index remains valid; wrong filler cannot be reserved even after transport.
        self.start_upload_process();raw=b'x'*70000
        q=self.uclient.begin('index',self.rpin.index_id,raw,h('large'))
        token=q[0];self.uclient.stream(token,raw)
        self.assertEqual(self.uclient.progress(token)[1],len(raw))
        self.err(None,lambda:self.uclient.reserve(token,self.bundle.index,self.rpin,30,h('reserve')))
    def test_read_client_cannot_mutate(self):
        self.start_upload_process();self.err('METHOD_DENIED',lambda:self.client._call('seal',h('lease')))
    def test_read_request_to_upload_socket_rejected(self):
        self.start_upload_process();c=self.ipc.Client(self.upload_path,self.p,self.kp,self.cs,self.cap)
        self.err(None,lambda:c.status(h('lease')))
    def test_upload_request_to_read_socket_rejected(self):
        self.start_upload_process();c=self.uc.Client(self.socket_path,self.p,self.kp,self.cs,self.cap)
        self.err(None,lambda:c.begin('index',self.rpin.index_id,self.bundle.index,h('idx')))
    def test_wrong_pinned_keeper_rejected(self):
        self.start_upload_process();c=self.uc.Client(self.upload_path,self.p,h('wrong'),self.cs,self.cap)
        self.err(None,lambda:c.begin('index',self.rpin.index_id,self.bundle.index,h('idx')))
    def test_unauthorized_client_does_not_crash_server(self):
        self.start_upload_process();cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,['get'],60,h('read'))
        c=self.uc.Client(self.upload_path,self.p,self.kp,self.cs,cap);self.err(None,lambda:c.begin('index',self.rpin.index_id,self.bundle.index,h('idx')))
        self.send_bundle();self.assertEqual(self.client.status(self.lid)['generation'],1)
    def test_oversized_frame_does_not_stop_server(self):
        self.start_upload_process()
        from par_keeper_service.transport import receive
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.upload_path));receive(s,4096,time.monotonic()+2)
        s.sendall((pr.MAX_REQUEST+1).to_bytes(4,'big'));s.close()
        self.send_bundle();self.assertEqual(self.client.status(self.lid)['generation'],1)
    def test_partial_then_disconnect(self):
        self.start_upload_process();token,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'))
        from par_keeper_service.transport import receive,frame
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.upload_path));hello=receive(s,4096,time.monotonic()+2)
        cmd=self.cmd('chunk',[token,0,self.bundle.index]);req=pr.make_request(self.p,self.cs,hello,cmd)
        s.sendall(frame(req,pr.MAX_REQUEST)[:-5]);s.close()
        self.assertEqual(self.uclient.progress(token)[1],0)
    def test_retry_after_reserve_response_not_read(self):
        self.start_upload_process();token,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'));self.uclient.stream(token,self.bundle.index)
        c=self.uclient.reserve_command(token,self.bundle.index,self.rpin,30,h('res'))
        from par_keeper_service.transport import receive,send
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.upload_path));hello=receive(s,4096,time.monotonic()+2)
        req=pr.make_request(self.p,self.cs,hello,c);send(s,req,pr.MAX_REQUEST,time.monotonic()+2);s.shutdown(socket.SHUT_WR)
        # Wait until a signed response is available, but discard it rather than acknowledge it.
        self.assertTrue(select.select([s],[],[],3)[0]);s.close()
        first=self.uclient.execute(c);self.assertEqual(self.uclient.execute(c),first)
    def test_restart_full_retry(self):
        self.start_upload_process();lid,rc=self.send_bundle();self.stop_process();self.start_upload_process()
        self.assertEqual(self.send_bundle(),(lid,rc))

    def test_sigkill_server_after_acknowledged_chunk(self):
        self.start_upload_process();token,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('crash-index'))
        self.uclient.chunk(token,0,self.bundle.index[:24]);ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)}
        rc,_,_=self.stop_process(kill=True);self.assertEqual(rc,-signal.SIGKILL)
        for path,identity in ids.items():self.ipc.recover_stale(path,identity)
        self.start_upload_process();self.assertEqual(self.uclient.progress(token)[1],24)
        self.uclient.stream(token,self.bundle.index);self.assertEqual(self.uclient.progress(token)[1],len(self.bundle.index))
    def test_sigkill_server_during_unfinished_request(self):
        self.start_upload_process();token,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('crash-index'))
        ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)}
        from par_keeper_service.transport import receive,frame
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            s.connect(str(self.upload_path));hello=receive(s,4096,time.monotonic()+2)
            cmd=self.cmd('chunk',[token,0,self.bundle.index]);packet=frame(pr.make_request(self.p,self.cs,hello,cmd),pr.MAX_REQUEST)
            s.sendall(packet[:-4]);rc,_,_=self.stop_process(kill=True);self.assertEqual(rc,-signal.SIGKILL)
        finally:s.close()
        for path,identity in ids.items():self.ipc.recover_stale(path,identity)
        self.start_upload_process();self.assertEqual(self.uclient.progress(token)[1],0)
    def test_convenience_chunk_invalid_input_is_coded(self):
        from par_keeper_upload.client import Client
        c=Client(self.upload_path,self.p,self.kp,self.cs,self.cap)
        for bad in (None,'text',[1,2],True):self.err(None,lambda bad=bad:c.chunk(h('token'),0,bad))
    def test_convenience_stream_invalid_input_is_coded(self):
        from par_keeper_upload.client import Client
        c=Client(self.upload_path,self.p,self.kp,self.cs,self.cap)
        self.err('PROTOCOL_SCHEMA',lambda:c.stream(h('token'),None))
