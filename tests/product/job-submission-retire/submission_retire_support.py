import importlib
from unittest.mock import patch
from submit_support import SubmitTest,h
class RetireTest(SubmitTest):
    def setUp(self):
        super().setUp();self.st.close();self.st=None
        try:self.rm=importlib.import_module('par_submit_retire.store');self.rc=importlib.import_module('par_submit_retire.contract')
        except ModuleNotFoundError:self.rm=None
        self.assertIsNotNone(self.rm,'submission retirement implementation missing')
        self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,migrate_legacy=True)
    def reopen(self,**kw):
        self.st.close();self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,**kw);return self.st
    def retire_request(self,d,operator=None,origin=None,revision=None,previous=None):
        prop=self.st.proposal(d)
        if previous is None:previous=prop.pop('previous')
        else:prop.pop('previous')
        return self.rc.make_request(self.p,operator or self.os,origin or self.os,revision=revision or self.ctl.policy()[1],previous=previous,nonce=h('retire-nonce'),**prop)
    def partial(self):
        r=self.payload();d=self.descriptor(r);self.st.begin(d);self.st.chunk(d,0,r[:17]);return d,r
    def stop_at(self,event,func):
        def stop(e):
            if e==event:raise RuntimeError('synthetic interruption')
        self.st.observer=stop
        try:self.err(None,func)
        finally:self.st.observer=None
