"""Disposable service fixture; public synthetic keys only."""
import importlib,json,os,select,signal,socket,subprocess,sys,time
from pathlib import Path
from repair_support import RepairTest,h
from par_keeper.contract import authority_body
from par_wire.codec import encode
ROOT=Path(__file__).resolve().parents[3]

class ServiceTest(RepairTest):
    def setUp(self):
        super().setUp();self.ipc=importlib.import_module('par_keeper_service')
        self.assertTrue(hasattr(self.ipc,'Server'),'Private service server is not implemented')
        self.socket_dir=Path(self.tmp.name)/'ipc';self.socket_dir.mkdir(mode=0o700);self.socket_path=self.socket_dir/'keeper.sock'
        self.server=None;self.process=None;self.c=None
    def tearDown(self):
        if getattr(self,'process',None) is not None:self.stop_process()
        if getattr(self,'server',None) is not None:self.server.close();self.server=None
        if getattr(self,'c',None) is not None:self.c.close()
        super().tearDown()
    def err(self,code,fn):
        with self.assertRaises(Exception) as c:fn()
        self.assertTrue(hasattr(c.exception,'code'),repr(c.exception))
        if code:self.assertEqual(c.exception.code,code)
    def start_local(self,**kw):
        lid,_=self.ready();self.lid=lid
        self.server=self.ipc.Server(self.keeper,self.socket_path,**kw)
        return lid
    def connect_local(self):
        c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.connect(str(self.socket_path));c.settimeout(1)
        self.c=c;self.server.poll(.05);self.server.poll(.05)
        hello=self.ipc.receive(c,self.ipc.MAX_HELLO,time.monotonic()+1)
        return c,hello
    def request_raw(self,hello,action='get',payload=None,cap=None):
        from par_keeper import make_call
        cap=cap or self.cap
        if action=='get' and payload is None:payload=sorted(self.bundle.objects)[0]
        self.counter+=1
        call=make_call(self.p,self.cs,cap,action,self.lid,h('ipc-call-'+str(self.counter)),payload)
        return self.ipc.make_request(self.p,self.cs,hello,cap,call,action,self.lid,payload)
    def pump(self,n=8):
        for _ in range(n):self.server.poll(.01)
    def config(self):
        path=Path(self.tmp.name)/'host.cbor'
        path.write_bytes(encode({0:1,1:authority_body(self.authority),2:self.total*3,3:32,4:4096}));path.chmod(0o600);return path
    def start_process(self,*,existing=False,deadline_ms=2000,max_connections=8,allow_legacy=True):
        if not existing:self.lid,_=self.ready()
        config=self.config()
        if self.keeper is not None:self.keeper.close();self.keeper=None
        args=[sys.executable,'-I','-S',str(ROOT/'tools/keeper_service_host.py'),'--root',str(self.path),'--socket',str(self.socket_path),'--host-config',str(config),'--key-fd','0','--deadline-ms',str(deadline_ms),'--max-connections',str(max_connections)]
        if allow_legacy:args+=['--allow-unpatched-sqlite','--allow-legacy-sodium']
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,env={'PATH':os.environ.get('PATH','')})
        self.process.stdin.write(self.ks);self.process.stdin.close();self.process.stdin=None
        if not select.select([self.process.stdout],[],[],6)[0]:raise AssertionError('host did not start')
        line=self.process.stdout.readline()
        if not line:
            err=self.process.stderr.read().decode();raise AssertionError('host startup failed: '+err)
        self.ready_message=json.loads(line)
        self.client=self.ipc.Client(self.socket_path,self.p,self.kp,self.cs,self.cap,timeout=3)
        return self.lid
    def stop_process(self,kill=False):
        p=self.process
        if p is None:return
        if p.poll() is None:
            p.send_signal(signal.SIGKILL if kill else signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
        out=p.stdout.read().decode();err=p.stderr.read().decode()
        p.stdout.close();p.stderr.close();self.process=None
        self.host_exit=(p.returncode,out,err)
        return self.host_exit
