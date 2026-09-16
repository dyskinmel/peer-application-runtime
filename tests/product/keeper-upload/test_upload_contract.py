import importlib,unittest,hashlib
from keeper_support import ContractTest,h
from par_wire.codec import encode,decode
from par_keeper.contract import make_call
class UploadContract(ContractTest):
    def setUp(self):
        super().setUp()
        try:self.u=importlib.import_module('par_keeper_upload.protocol')
        except ModuleNotFoundError:self.u=None
        self.assertTrue(self.u is not None,'Private upload protocol not implemented')
        self.capability=self.cap();self.hello=self.u.make_hello(self.p,self.seed,h('boot'),h('challenge'),5000)
    def begin(self,**kw):
        body=kw.pop('payload',['index',self.index,250,h('sha')])
        return self.u.make_command(self.p,self.subject,self.capability,'begin',h('op'),None,None,body,**kw)
    def test_roundtrip(self):
        c=self.begin();raw=self.u.make_request(self.p,self.subject,self.hello,c)
        self.assertEqual(self.u.check_request(self.p,self.pk,self.hello,raw),c)
    def test_fixed_methods(self):self.assertEqual(self.u.METHODS,frozenset(('begin','chunk','progress','reserve','put','seal')))
    def test_read_allowlist_unchanged(self):
        from par_keeper_service import METHODS
        self.assertEqual(METHODS,frozenset(('get','status','receipt','challenge')))
    def test_hello_signature(self):
        b=bytearray(self.hello);b[-1]^=1;self.err(None,lambda:self.u.check_hello(self.p,self.pk,bytes(b)))
    def test_hello_wrong_keeper(self):self.err(None,lambda:self.u.check_hello(self.p,h('wrong'),self.hello))
    def test_replayed_connection_rejected(self):
        raw=self.u.make_request(self.p,self.subject,self.hello,self.begin())
        hello=self.u.make_hello(self.p,self.seed,h('boot'),h('new'),5000)
        self.err(None,lambda:self.u.check_request(self.p,self.pk,hello,raw))
    def test_changed_stable_command(self):
        c=self.begin();o=decode(c);b=decode(o[0]);b[3]=h('changed');o[0]=encode(b)
        self.err(None,lambda:self.u.check_command(self.p,encode(o)))
    def test_wrong_subject(self):self.err(None,lambda:self.u.make_command(self.p,h('wrong'),self.capability,'begin',h('op'),None,None,['index',self.index,250,h('sha')]))
    def test_read_protocol_not_accepted(self):
        from par_keeper_service import make_hello
        raw=make_hello(self.p,self.seed,h('boot'),h('nonce'),5000)
        self.err(None,lambda:self.u.check_hello(self.p,self.pk,raw))
    def test_response_binding(self):
        q=self.u.make_request(self.p,self.subject,self.hello,self.begin())
        r=self.u.make_response(self.p,self.seed,self.hello,q,True,b'yes')
        self.assertEqual(self.u.check_response(self.p,self.pk,self.hello,q,r),b'yes')
        self.err(None,lambda:self.u.check_response(self.p,self.pk,self.hello,q+b'x',r))
    def test_signed_error(self):
        q=self.u.make_request(self.p,self.subject,self.hello,self.begin())
        r=self.u.make_response(self.p,self.seed,self.hello,q,False,'REJECTED')
        self.err(None,lambda:self.u.check_response(self.p,self.pk,self.hello,q,r))
    def err(self,code,fn):
        with self.assertRaises(Exception) as cm:fn()
        self.assertTrue(hasattr(cm.exception,'code'),repr(cm.exception))
        if code:self.assertEqual(cm.exception.code,code)

def bad_method(name):
    def test(self):self.err(None,lambda:self.u.make_command(self.p,self.subject,self.capability,name,h('op'),None,None,None))
    return test
for name in ('get','renew','release','repair','collect','update_authority','__dict__','exec'):
    setattr(UploadContract,'test_denied_method_'+name.replace('_','x'),bad_method(name))

def malformed(value):
    def test(self):self.err(None,lambda:self.begin(payload=value))
    return test
for label,val in {'unknown_kind':['path','x',1,h('s')],'zero':['index',h('x'),0,h('s')],'boolean':['index',h('x'),True,h('s')],'too_big':['index',h('x'),1048577,h('s')],'bad_hash':['index',h('x'),5,b'x'],'path':['index','../x',5,h('s')],'extra':['index',h('x'),5,h('s'),0]}.items():setattr(UploadContract,'test_begin_'+label,malformed(val))
