"""Synthetic local repair fixtures; not user keys or network peers."""
import importlib
from pathlib import Path
from dataclasses import replace
from gc_support import GCTest,h
from par_keeper.contract import split

class RepairTest(GCTest):
    def setUp(self):
        super().setUp()
        try:self.r=importlib.import_module('par_keeper_repair')
        except ModuleNotFoundError:self.r=None
        self.assertTrue(self.r is not None and hasattr(self.r,'KeeperRepair'),'Keeper repair not implemented')
    def open_keeper(self,**kw):
        self.keeper=self.r.KeeperRepair(self.path,self.p,self.ks,self.authority,quota_bytes=kw.pop('quota_bytes',self.total*3),clock=self.clock,allow_unpatched_sqlite=True,**kw)
        return self.keeper
    def repair_request(self,lid,oids=None,nonce=None,cap=None,seed=None):
        self.counter+=1
        return self.r.make_request(self.p,seed or self.cs,cap or self.cap,lid,self.keeper._lease(lid)['generation'],self.rpin.index_id,
            list(oids if oids is not None else sorted(self.bundle.objects)[:1]),nonce or h('repair-'+str(self.counter)))
    def repair(self,lid,req,objects=None,cap=None):
        v,_=split(req)
        objs={oid:self.bundle.objects[oid] for oid in v[8]} if objects is None else objects
        return self.keeper.repair(lid,objs,cap or self.cap,req)
    def damage(self,lid,kind='missing',oid=None):
        oid=oid or sorted(self.bundle.objects)[0];p=self.keeper.object_path(lid,oid)
        if kind=='missing':p.unlink()
        elif kind=='empty':p.write_bytes(b'')
        else:p.write_bytes(b'X'*len(self.bundle.objects[oid]))
        return oid
    def cancel_request(self,lid,job,cap=None,nonce=None):
        self.counter+=1
        return self.r.make_cancel(self.p,self.cs,cap or self.cap,lid,job,nonce or h('cancel-'+str(self.counter)))
