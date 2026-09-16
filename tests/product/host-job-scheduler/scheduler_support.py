"""Real synthetic Keeper/ReplaySpool and private sockets. No detached workers."""
import importlib,socket,time
from pathlib import Path
from host_support import HostTest,h
from par_keeper_service.transport import receive,send
class SchedulerTest(HostTest):
    def setUp(self):
        super().setUp();self.host=None;self.sockets=[]
        try:self.m=importlib.import_module('par_job_scheduler')
        except ModuleNotFoundError:self.m=None
        self.assertTrue(self.m is not None and hasattr(self.m,'ScheduledHost'),'ScheduledHost not implemented')
        self.jroot=Path(self.tmp.name)/'scheduled-jobs'
    def tearDown(self):
        for s in getattr(self,'sockets',[]):s.close()
        if getattr(self,'host',None) is not None:self.host.close();self.host=None
        super().tearDown()
    def start_host(self,**kw):
        self.host=self.m.ScheduledHost(self.keeper,self.window,self.socket_path,self.upload_path,self.jroot,**kw)
        return self.host
    def jid(self,label='one'):return h('scheduled-'+label)
    def submit_close(self):
        a,q=self.proposed();return self.host.submit(self.jid(),action='close',command=q,archive=a)
    def tick(self,n=1):
        r=None
        for _ in range(n):r=self.host.tick(0)
        return r
    def connect(self,upload=False):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(.5);s.connect(str(self.upload_path if upload else self.socket_path));self.sockets.append(s)
        self.tick(2)
        return s,receive(s,4096,time.monotonic()+.5)
    def ready_keeper(self):
        self.lid=self.reserve();self.fill(self.lid);self.seal(self.lid);return self.lid
    def complete(self):
        for _ in range(8):
            self.tick();r=self.host.jobs.poll(self.jid())
            if r['state']=='SUCCEEDED':return r
        self.fail(str(self.host.diagnostics()))
