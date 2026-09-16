from host_process_support import *

class HostProcess(ProcessTest):
    def test_partial_upload_survives_restart(self):
        self.start_host();t,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'));self.uclient.chunk(t,0,self.bundle.index[:20]);self.stop_process();self.start_host()
        self.assertEqual(self.uclient.progress(t)[1],20);self.uclient.stream(t,self.bundle.index)
    def test_legacy_client_rejected_new_socket(self):
        from par_keeper_upload.client import Client
        self.start_host();c=Client(self.upload_path,self.p,self.kp,self.cs,self.cap)
        self.err(None,lambda:c.begin('index',self.rpin.index_id,self.bundle.index,h('legacy')))
        self.send_bundle()
    def test_data_client_rejected_read_socket(self):
        self.start_host();c=self.cpmod.Client(self.socket_path,self.p,self.kp,self.cs,self.cap,self.store_id,self.grant)
        self.err(None,lambda:c.begin('index',self.rpin.index_id,self.bundle.index,h('wrong')))
    def test_wrong_store_before_connection(self):
        self.err('WINDOW_SCOPE',lambda:self.cpmod.Client(self.upload_path,self.p,self.kp,self.cs,self.cap,h('wrong'),self.grant))
    def test_admin_cannot_acquire_running_host(self):
        self.start_host();cp=self.admin('inspect',expect=1);self.assertIn(b'WRITER_BUSY',cp.stderr)
        self.send_bundle()
    def test_host_cannot_acquire_active_local_gateway(self):
        cp=subprocess.run(self.host_args(),input=self.ks,capture_output=True,timeout=6)
        self.assertNotEqual(cp.returncode,0);self.assertFalse(self.upload_path.exists())
    def test_closed_host_does_not_auto_open(self):
        self.finish();self.write_cfg();self.start_host()
        self.err('WINDOW_CLOSED',lambda:self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx')))
    def test_partial_request_no_operation(self):
        self.start_host();q=self.uclient.command('begin',h('idx'),['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()])
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            s.connect(str(self.upload_path));hello=receive(s,4096,time.monotonic()+2);packet=frame(self.hp.make_request(self.p,self.cs,hello,self.grant,q),65536);s.sendall(packet[:-1])
        finally:s.close()
        self.stop_process();self.assertEqual(len(list((self.wroot/'bindings').iterdir())),0)
    def test_lost_reserve_response_retry_same_id(self):
        self.start_host();t,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'));self.uclient.stream(t,self.bundle.index)
        q=self.uclient.reserve_command(t,self.bundle.index,self.rpin,30,h('res'))
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            s.connect(str(self.upload_path));hello=receive(s,4096,time.monotonic()+2);send(s,self.hp.make_request(self.p,self.cs,hello,self.grant,q),65536,time.monotonic()+2)
            self.assertTrue(select.select([s],[],[],3)[0])
        finally:s.close()
        first=self.uclient.execute(q);self.assertEqual(first,self.uclient.execute(q))
    def test_missing_spool_rejected_without_creation(self):
        self.window.close();self.window=None;self.keeper.close();self.keeper=None
        args=self.host_args();args[args.index('--spool')+1]=str(Path(self.tmp.name)/'absent')
        cp=subprocess.run(args,input=self.ks,capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertFalse((Path(self.tmp.name)/'absent').exists())
    def test_config_permissions_rejected(self):
        self.cfgpath.chmod(0o644);cp=subprocess.run(self.host_args(),input=self.ks,capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertFalse(self.upload_path.exists())
    def test_wrong_keeper_key_rejected(self):
        cp=subprocess.run(self.host_args(),input=h('wrong'),capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertIn(b'KEEPER_IDENTITY',cp.stderr)
    def test_admin_unknown_action_rejected(self):self.err('METHOD_DENIED',lambda:self.hmod.administer(self.window,'delete-everything'))
    def test_admin_data_command_cannot_be_retirement(self):self.err('METHOD_DENIED',lambda:self.hmod.administer(self.window,'retire',command=self.command()))
