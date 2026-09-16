import importlib
from pathlib import Path
from scheduler_support import SchedulerTest,h
from par_job_control.controller import Controller
class SubmitTest(SchedulerTest):
    def setUp(self):
        super().setUp();self.st=None;self.ctl=None
        try:self.sc=importlib.import_module('par_job_submit.protocol');self.sm=importlib.import_module('par_job_submit.staging')
        except ModuleNotFoundError:self.sc=None
        self.assertIsNotNone(self.sc,'signed staged submission is not implemented')
        self.start_host();self.os=h('submit-operator');self.op=self.p.sign_public(self.os)
        self.ctl=Controller(self.host,Path(self.tmp.name)/'controller',self.op,1)
        self.sroot=Path(self.tmp.name)/'submissions';self.st=self.sm.Submissions(self.ctl,self.sroot)
    def tearDown(self):
        if getattr(self,'st',None):self.st.close();self.st=None
        if getattr(self,'ctl',None):self.ctl.close();self.ctl=None
        super().tearDown()
    def payload(self):
        a,q=self.proposed();return self.sc.pack_job('close',q,a)
    def descriptor(self,raw=None,jid=None,**kw):
        raw=self.payload() if raw is None else raw
        d=dict(keeper=self.kp,store=self.store_id,revision=1,job_id=jid or self.jid(),target=self.st.target(),size=len(raw),payload_hash=self.sc.sha(raw));d.update(kw)
        return self.sc.make_descriptor(self.p,self.os,**d)
    def ready(self,raw=None,jid=None):
        raw=self.payload() if raw is None else raw;desc=self.descriptor(raw,jid);self.st.begin(desc)
        for off in range(0,len(raw),self.sc.CHUNK):self.st.chunk(desc,off,raw[off:off+self.sc.CHUNK])
        return desc,raw
    def reopen(self,**kw):
        self.st.close();self.st=self.sm.Submissions(self.ctl,self.sroot,**kw);return self.st
