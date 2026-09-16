"""Synthetic fixtures only. Never detached children or user data."""
import importlib, hashlib
from window_support import WindowTest,h,pr
class HostTest(WindowTest):
    def setUp(self):
        try:self.hp=importlib.import_module('par_window_host.protocol')
        except ModuleNotFoundError:self.hp=None
        self.assertIsNotNone(self.hp,'generation-bound host contract is not implemented')
        super().setUp()
        self.upload_path=self.socket_dir/'window.sock'
    def hello(self,**kw):
        d=dict(store=self.store_id,window=self.grant,phase='OPEN',boot=h('boot'),challenge=h('challenge'),deadline_ms=1000);d.update(kw)
        return self.hp.make_hello(self.p,self.ks,**d)
    def command(self,action='begin',payload=None):
        if payload is None and action=='begin':payload=['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()]
        return self.wrap(self.cmd(action,payload))
    def host_request(self,hello=None,command=None):
        return self.hp.make_request(self.p,self.cs,hello or self.hello(),self.grant,command or self.command())
