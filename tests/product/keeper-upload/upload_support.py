"""Disposable synthetic fixtures. No user keys, remote targets or detachment."""
import hashlib,importlib
from pathlib import Path
from service_support import ServiceTest,h
from par_keeper.contract import make_call,reserve_payload,put_payload,pin_values,split
from par_keeper_upload import protocol as pr

class UploadTest(ServiceTest):
    def setUp(self):
        super().setUp()
        try:m=importlib.import_module('par_keeper_upload.spool')
        except ModuleNotFoundError:m=None
        self.assertTrue(m is not None and hasattr(m,'Spool'),'Upload spool not implemented')
        self.spooltype=m.Spool;self.spool=None;self.open_keeper()
        self.stage_root=self.path/'incoming-upload'
        self.spool=self.spooltype(self.keeper,self.stage_root)
    def tearDown(self):
        if getattr(self,'spool',None) is not None:self.spool.close();self.spool=None
        super().tearDown()
    def cmd(self,action,payload=None,lease=None,call=None,nonce=None,cap=None):
        self.counter+=1
        return pr.make_command(self.p,self.cs,cap or self.cap,action,nonce or h('cmd-'+str(self.counter)),call,lease,payload)
    def begin_index(self,nonce=None):
        raw=self.bundle.index
        self.beginraw=self.cmd('begin',['index',self.rpin.index_id,len(raw),hashlib.sha256(raw).digest()],nonce=nonce)
        return self.spool.execute(self.beginraw)[0]
    def chunks(self,token,raw,lease=None,size=pr.CHUNK):
        result=None
        for offset in range(0,len(raw),size):result=self.spool.execute(self.cmd('chunk',[token,offset,raw[offset:offset+size]],lease))
        return result
    def upload_index(self):
        token=self.begin_index();self.chunks(token,self.bundle.index)
        self.rescall=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30))
        self.rescmd=self.cmd('reserve',[token,pin_values(self.rpin),30],call=self.rescall)
        self.lid=self.spool.execute(self.rescmd);return self.lid
    def begin_object(self,lid,oid=None):
        oid=oid or sorted(self.bundle.objects)[0];raw=self.bundle.objects[oid]
        self.putcall=self.call('put',lid,put_payload(oid,raw))
        self.object_begin=self.cmd('begin',['object',oid,len(raw),hashlib.sha256(raw).digest()],lid,self.putcall)
        token=self.spool.execute(self.object_begin)[0]
        return token,oid,raw,self.putcall
    def upload_object(self,lid,oid):
        token,oid,raw,call=self.begin_object(lid,oid);self.chunks(token,raw,lid)
        self.putcmd=self.cmd('put',token,lid,call);self.spool.execute(self.putcmd);return token
    def upload_all(self):
        lid=self.upload_index()
        for oid in self.bundle.objects:self.upload_object(lid,oid)
        self.sealcall=self.call('seal',lid)
        self.sealcmd=self.cmd('seal',None,lid,self.sealcall)
        self.rc=self.spool.execute(self.sealcmd);return lid
    def reopen(self):
        self.spool.close();self.spool=self.spooltype(self.keeper,self.stage_root);return self.spool
