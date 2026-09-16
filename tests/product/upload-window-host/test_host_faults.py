from host_process_support import *

class HostFaults(ProcessTest):
    def test_sigkill_after_chunk_ack(self):
        self.start_host();t,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'));self.uclient.chunk(t,0,self.bundle.index[:20])
        ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)};self.assertEqual(self.stop_process(kill=True)[0],-signal.SIGKILL);self.recover_sockets(ids)
        self.start_host();self.assertEqual(self.uclient.progress(t)[1],20);self.uclient.stream(t,self.bundle.index)
    def test_sigkill_before_complete_request(self):
        self.start_host();s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)}
        try:s.connect(str(self.upload_path));receive(s,4096,time.monotonic()+2);s.sendall(b'\0\0');self.assertEqual(self.stop_process(kill=True)[0],-signal.SIGKILL)
        finally:s.close()
        self.recover_sockets(ids);self.start_host();self.send_bundle()
    def test_sigkill_after_seal_ack(self):
        self.start_host();result=self.send_bundle();ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)};self.assertEqual(self.stop_process(kill=True)[0],-signal.SIGKILL);self.recover_sockets(ids)
        self.start_host();self.assertEqual(self.send_bundle(),result)
