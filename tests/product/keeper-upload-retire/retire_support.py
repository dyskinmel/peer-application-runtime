"""Public synthetic fixture only. No user data or external connections."""
import importlib
from dataclasses import replace
from upload_support import UploadTest,h,pr
from par_keeper.contract import authority_body
class RetireTest(UploadTest):
    def setUp(self):
        super().setUp()
        try:module=importlib.import_module('par_keeper_upload_retire')
        except ModuleNotFoundError:module=None
        self.assertTrue(module is not None and hasattr(module,'RetiringSpool'),'Retirement candidate not implemented')
        self.ret=module
        self.spool.close();self.spooltype=module.RetiringSpool
        self.spool=self.spooltype(self.keeper,self.stage_root,allow_migrate=True)
    def retirement_request(self,begin=None,operation=None,authority=None,issuer_seed=None,subject_seed=None):
        self.counter+=1
        g=self.ret.issue_grant(self.p,issuer_seed or self.s.owner,authority or self.keeper.authority,self.kp,begin or self.beginraw,h('retire-grant-'+str(self.counter)))
        return self.ret.make_request(self.p,subject_seed or self.cs,g,operation or h('retire-op-'+str(self.counter)))
    def change_authority(self):
        a=replace(self.keeper.authority,head=h('new-head-'+str(self.counter)),sequence=self.keeper.authority.sequence+1)
        self.counter+=1;self.keeper.update_authority(a);self.authority=a;return a
    def part(self,t):return self.stage_root/(t.hex()+'.part')
