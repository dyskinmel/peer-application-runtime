"""Synthetic local fixtures, inherited crypto/SQLite opt-in. No network."""
import hashlib, importlib
from pathlib import Path
from retire_support import RetireTest,h,pr
from par_keeper.contract import reserve_payload,pin_values
class WindowTest(RetireTest):
    def setUp(self):
        super().setUp()
        try:self.w=importlib.import_module('par_upload_window')
        except ModuleNotFoundError:self.w=None
        self.assertTrue(self.w is not None and hasattr(self.w,'ReplaySpool'),'Replay window candidate not implemented')
        self.spool.close();self.spool=None
        self.wroot=self.path/'window-spool';self.store_id=h('window-spool-id');self.window=None
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id)
        self.grant=self.grant_for(1,None);self.window.open_window(self.grant)
    def tearDown(self):
        if getattr(self,'window',None) is not None:self.window.close();self.window=None
        super().tearDown()
    def grant_for(self,seq,previous,nonce=None,authority=None):
        return self.w.make_window(self.p,self.s.owner,authority or self.keeper.authority,self.kp,self.store_id,seq,nonce or h('gen-'+str(seq)),previous)
    def wrap(self,raw,kind='execute',grant=None):
        return self.w.wrap_command(self.p,self.cs,grant or self.grant,kind,raw)
    def execute(self,raw):return self.window.execute(self.wrap(raw))
    def upload_stage(self,n=0):
        self.beginraw=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()])
        self.beginwrapped=self.wrap(self.beginraw);t=self.window.execute(self.beginwrapped)[0]
        if n:self.execute(self.cmd('chunk',[t,0,self.bundle.index[:n]]))
        return t
    def retire_stage(self):
        raw=self.retirement_request();return self.window.execute(self.wrap(raw,'retire'))
    def terminal(self):
        t=self.upload_stage(8);self.retire_stage();return t
    def complete_index(self):
        t=self.upload_stage(len(self.bundle.index));call=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30))
        raw=self.cmd('reserve',[t,pin_values(self.rpin),30],call=call);lid=self.execute(raw)
        return t,lid
    def proposed(self):
        raw=self.window.export_archive()
        close=self.w.approve_close(self.p,self.s.owner,self.keeper.authority,self.grant,raw,h('close-'+str(self.counter)))
        return raw,close
    def finish(self):
        raw,req=self.proposed();self.window.close_window(req,raw);return self.window.compact()
    def reopen_window(self,**kw):
        self.window.close();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,**kw);return self.window
    def next_window(self,receipt=None):
        receipt=receipt or self.finish();seq=self.w.check_window(self.p,self.grant)[5]+1
        self.grant=self.grant_for(seq,self.w.digest(receipt));self.window.open_window(self.grant)
    def live(self,t,suffix='.cbor'):return self.wroot/'live'/(t.hex()+suffix)
    def err(self,code,fn):
        with self.assertRaises(Exception) as cm:fn()
        self.assertTrue(hasattr(cm.exception,'code'),repr(cm.exception))
        if code:self.assertEqual(cm.exception.code,code)
