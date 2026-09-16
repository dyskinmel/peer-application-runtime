"""Synthetic isolated GC test environment. No network or user data."""
import importlib
from pathlib import Path
from keeper_support import KeeperTest, h

class GCTest(KeeperTest):
    def setUp(self):
        super().setUp()
        try:self.g=importlib.import_module('par_keeper_gc')
        except ModuleNotFoundError:self.g=None
        self.assertTrue(self.g is not None and hasattr(self.g,'KeeperGC'),'Keeper GC not implemented')
    def open_keeper(self,**kw):
        self.keeper=self.g.KeeperGC(self.path,self.p,self.ks,self.authority,
            quota_bytes=kw.pop('quota_bytes',self.total*3),clock=self.clock,allow_unpatched_sqlite=True,**kw)
        return self.keeper
    def gc_request(self,lid,*,nonce=None,cap=None,seed=None,generation=None,release_id=None):
        self.counter+=1
        target=self.keeper.gc_target(lid)
        return self.g.make_request(self.p,seed or self.cs,cap or self.cap,lid,
            target['generation'] if generation is None else generation,
            target['release_id'] if release_id is None else release_id,
            nonce or h('gc-'+str(self.counter)))
    def released(self,**kw):
        lid,receipt=self.ready(**kw);self.release(lid)
        return lid,self.gc_request(lid)
    def gc(self,lid,req,cap=None):return self.keeper.collect(lid,cap or self.cap,req)
    def reopen(self,**kw):
        self.keeper.close();return self.open_keeper(**kw)
