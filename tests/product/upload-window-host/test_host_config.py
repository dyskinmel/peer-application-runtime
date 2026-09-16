import importlib
from host_support import HostTest,h
from par_keeper.contract import authority_body
class HostConfig(HostTest):
    def setUp(self):
        super().setUp()
        try:self.host=importlib.import_module('par_window_host.host')
        except ModuleNotFoundError:self.host=None
        self.assertIsNotNone(self.host,'window host config is not implemented')
        self.cfg={0:1,1:self.hp.PROFILE,2:self.kp,3:authority_body(self.keeper.authority),4:self.total*3,5:32,6:4096,7:self.store_id,8:self.window.pin(),9:16*1024*1024,10:1024,11:64*1024*1024,12:64}
    def test_config_roundtrip(self):self.assertEqual(self.host.check_config(self.cfg),self.cfg)
    def test_no_unknown_fields(self):self.cfg[13]='extra';self.err(None,lambda:self.host.check_config(self.cfg))
    def test_no_boolean_version(self):self.cfg[0]=True;self.err(None,lambda:self.host.check_config(self.cfg))
    def test_no_legacy_profile(self):self.cfg[1]='keeper-upload-local-v1';self.err(None,lambda:self.host.check_config(self.cfg))
    def test_pin_store_consistent(self):self.cfg[8][0]=h('other');self.err(None,lambda:self.host.check_config(self.cfg))
    def test_pin_required(self):self.cfg[8]=None;self.err(None,lambda:self.host.check_config(self.cfg))
    def test_unknown_pin_fields(self):self.cfg[8][4]=0;self.err(None,lambda:self.host.check_config(self.cfg))
    def test_bound_records(self):self.cfg[10]=1025;self.err(None,lambda:self.host.check_config(self.cfg))
    def test_no_boolean_limits(self):self.cfg[12]=True;self.err(None,lambda:self.host.check_config(self.cfg))
    def test_snapshot_not_mutable_alias(self):
        result=self.host.check_config(self.cfg);self.cfg[8][1]=55;self.assertEqual(result[8][1],1)
