"""Synthetic local owner/controller fixture. Never user data or a public listener."""
import importlib
from pathlib import Path
from scheduler_support import SchedulerTest,h
class ControlTest(SchedulerTest):
    def setUp(self):
        super().setUp()
        try:self.cm=importlib.import_module('par_job_control.controller')
        except ModuleNotFoundError:self.cm=None
        self.assertIsNotNone(self.cm,'Controller not implemented')
        from par_job_control import protocol
        self.pr=protocol;self.os=h('control-operator-public-test-seed');self.op=self.p.sign_public(self.os)
        self.cr=Path(self.tmp.name)/'control-journal';self.ctl=None
        self.start_host();self.submit_close()
        self.ctl=self.cm.Controller(self.host,self.cr,self.op,1)
    def tearDown(self):
        if getattr(self,'ctl',None):self.ctl.close();self.ctl=None
        super().tearDown()
    def intent(self,action='select',opid=None,jid='default',seed=None,rev=1):
        return self.pr.make_intent(self.p,seed or self.os,keeper=self.kp,store=self.store_id,revision=rev,operation_id=opid or h('op-'+action),action=action,job_id=self.jid() if jid=='default' else jid)
    def call(self,action='select',**kw):return self.ctl.execute(self.intent(action,**kw))
    def reopen_ctl(self,**kw):
        self.ctl.close();self.ctl=self.cm.Controller(self.host,self.cr,self.op,1,**kw)
        return self.ctl
