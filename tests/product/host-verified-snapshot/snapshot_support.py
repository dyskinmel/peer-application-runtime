"""Public synthetic test material and real pinned libsodium only."""
import importlib, unittest
from auth_support import provider,h

def module(test):
    try:m=importlib.import_module('par_verified_host')
    except ModuleNotFoundError:m=None
    test.assertTrue(m is not None and hasattr(m,'VerificationProvider'),'positive verification snapshot candidate is not implemented')
    return m

class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.m=module(self);self.base=provider();self.seed=h('snapshot-signing')
        self.pk=self.base.sign_public(self.seed);self.msg=b'PAR public synthetic verification snapshot'
        self.sig=self.base.sign(self.seed,self.msg)
        self.p=self.m.VerificationProvider(self.base,mode='signatures')
    def tearDown(self):
        if getattr(self,'p',None) is not None:self.p.close()
    def verify(self,**kw):
        return self.p.verify(kw.get('pk',self.pk),kw.get('msg',self.msg),kw.get('sig',self.sig))
    def err(self,code,fn):
        with self.assertRaises(Exception) as c:fn()
        self.assertEqual(getattr(c.exception,'code',None),code,repr(c.exception))
    def make(self,**kw):
        self.p.close();self.p=self.m.VerificationProvider(self.base,mode=kw.pop('mode','signatures'),**kw);return self.p
