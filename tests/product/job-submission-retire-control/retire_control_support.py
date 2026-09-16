import importlib,socket,time
from pathlib import Path
from submission_retire_support import RetireTest,h
from par_keeper_service.transport import receive,send
class ProtocolTest(RetireTest):
    def setUp(self):
        super().setUp()
        try:self.proto=importlib.import_module('par_submit_retire_control.protocol')
        except ModuleNotFoundError:self.proto=None
        self.assertIsNotNone(self.proto,'explicit retirement control protocol not implemented')
    def hello(self,revision=1,public=None,challenge=None):
        return self.sc.make_hello(self.p,self.ks,store=self.store_id,controller=public or self.op,revision=revision,boot=h('boot'),challenge=challenge or h('hello'),deadline_ms=500)
    def ext_request(self,action='proposal',desc=None,authorization=None,hello=None,seed=None):
        return self.proto.make_request(self.p,seed or self.os,hello or self.hello(),action,desc or self.descriptor(),authorization)
    def ext_check(self,raw,hello=None):
        public,rev=self.ctl.policy()
        return self.proto.check_request(self.p,self.kp,self.store_id,public,rev,hello or self.hello(),raw)
class SocketTest(ProtocolTest):
    def setUp(self):
        super().setUp();self.whole=None
        try:self.hm=importlib.import_module('par_submit_retire_control.host')
        except ModuleNotFoundError:self.hm=None
        self.assertIsNotNone(self.hm,'four-endpoint compatible retirement control host not implemented')
        self.st.close();self.ctl.close();self.host.close();self.st=self.ctl=self.host=None
        self.cpath=self.socket_dir/'control.sock';self.spath=self.socket_dir/'submit.sock';self.open_host()
    def open_host(self):
        self.whole=self.hm.RetirementControlHost(self.keeper,self.window,self.socket_path,self.upload_path,self.cpath,self.spath,self.jroot,Path(self.tmp.name)/'controller',self.sroot,self.op,1,submit_deadline_ms=500)
        self.host=self.whole.scheduler;self.ctl=self.whole.controller;self.st=self.whole.submissions
    def tearDown(self):
        if getattr(self,'whole',None):self.whole.close();self.whole=None;self.host=self.ctl=self.st=None
        super().tearDown()
    def connect(self):
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(2);self.sockets.append(sock);sock.connect(str(self.spath))
        self.whole.tick(0);self.whole.tick(0)
        return sock,receive(sock,self.sc.MAX_HELLO,time.monotonic()+2)
    def exchange(self,action,desc,authorization=None,*,legacy=False,offset=None,data=None,seed=None):
        sock,hi=self.connect()
        req=self.sc.make_request(self.p,seed or self.os,hi,action,desc,offset,data) if legacy else self.ext_request(action,desc,authorization,hi,seed)
        send(sock,req,self.sc.MAX_REQUEST,time.monotonic()+2)
        for _ in range(8):self.whole.tick(0)
        raw=receive(sock,self.sc.MAX_RESPONSE,time.monotonic()+2);sock.close()
        return (self.sc if legacy else self.proto).check_response(self.p,self.kp,hi,req,raw)
