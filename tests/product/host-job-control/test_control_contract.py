"""Public synthetic keys. Tests fix protocol scope before implementation."""
import importlib,unittest,hashlib
from pathlib import Path
from par_crypto.provider import SodiumProvider
from harness.common import read_json
ROOT=Path(__file__).resolve().parents[3]
h=lambda s:hashlib.sha256(s.encode()).digest()
class ControlContract(unittest.TestCase):
    def setUp(self):
        try:self.c=importlib.import_module('par_job_control.protocol')
        except ModuleNotFoundError:self.c=None
        self.assertIsNotNone(self.c,'job control protocol not implemented')
        self.p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=True)
        self.ks=h('control-test-keeper');self.cs=h('control-test-owner');self.kp=self.p.sign_public(self.ks);self.cp=self.p.sign_public(self.cs);self.store=h('store')
    def hello(self,**kw):
        args=dict(store=self.store,controller=self.cp,revision=1,boot=h('boot'),challenge=h('challenge'),deadline_ms=1000);args.update(kw)
        return self.c.make_hello(self.p,self.ks,**args)
    def intent(self,action='select',jid=None,**kw):
        args=dict(keeper=self.kp,store=self.store,revision=1,operation_id=h('op'),action=action,job_id=jid or h('job'));args.update(kw)
        return self.c.make_intent(self.p,self.cs,**args)
    def err(self,fn):
        with self.assertRaises(Exception) as cm:fn()
        self.assertTrue(hasattr(cm.exception,'code'),repr(cm.exception))
    def test_roundtrip_five_actions(self):
        for a in self.c.ACTIONS:
            hello=self.hello();intent=self.intent(a);raw=self.c.make_request(self.p,self.cs,hello,intent)
            b=self.c.check_request(self.p,self.kp,self.store,self.cp,1,hello,raw)
            self.assertEqual((b.action,b.job_id,b.operation_id),(a,h('job'),h('op')))
    def test_unknown_action_rejected(self):
        for a in ('submit','eval','shell','open','close','compact','__getattr__','http://example.com'):
            with self.subTest(a=a):self.err(lambda:self.intent(a))
    def test_null_job_only_status(self):
        for a in self.c.ACTIONS:
            kwargs=dict(keeper=self.kp,store=self.store,revision=1,operation_id=h('op'),action=a,job_id=None)
            if a=='status':self.c.make_intent(self.p,self.cs,**kwargs)
            else:self.err(lambda:self.c.make_intent(self.p,self.cs,**kwargs))
    def test_wrong_keeper(self):self.err(lambda:self.c.check_hello(self.p,h('other'),self.store,self.cp,1,self.hello()))
    def test_wrong_store(self):self.err(lambda:self.c.check_hello(self.p,self.kp,h('other'),self.cp,1,self.hello()))
    def test_wrong_controller(self):self.err(lambda:self.c.check_hello(self.p,self.kp,self.store,h('other'),1,self.hello()))
    def test_old_policy_revision(self):self.err(lambda:self.c.check_hello(self.p,self.kp,self.store,self.cp,2,self.hello()))
    def test_bool_revision_refused(self):self.err(lambda:self.hello(revision=True))
    def test_request_new_connection_refused(self):
        a=self.hello();req=self.c.make_request(self.p,self.cs,a,self.intent())
        self.err(lambda:self.c.check_request(self.p,self.kp,self.store,self.cp,1,self.hello(challenge=h('other')),req))
    def test_request_wrong_owner_refused(self):self.err(lambda:self.c.make_request(self.p,h('wrong'),self.hello(),self.intent()))
    def test_intent_signature_tamper(self):
        r=self.intent();self.err(lambda:self.c.check_intent(self.p,self.kp,self.store,self.cp,1,r[:-1]+bytes([r[-1]^1])))
    def test_same_intent_across_connections(self):
        i=self.intent();a=self.hello();b=self.hello(challenge=h('other'))
        self.assertNotEqual(self.c.make_request(self.p,self.cs,a,i),self.c.make_request(self.p,self.cs,b,i))
        self.assertEqual(self.c.check_intent(self.p,self.kp,self.store,self.cp,1,i).operation_id,h('op'))
    def test_noncanonical_and_trailing_refused(self):
        self.err(lambda:self.c.check_hello(self.p,self.kp,self.store,self.cp,1,self.hello()+b'\x00'))
    def test_wrong_id_size(self):
        for v in (b'',b'x'*31,'abcd',True,bytearray(32)):
            with self.subTest(t=type(v).__name__):self.err(lambda:self.intent(operation_id=v))
    def test_revoked_hello_not_usable(self):self.err(lambda:self.c.check_hello(self.p,self.kp,self.store,self.cp,1,self.hello(controller=None)))
    def test_limits_fixed(self):
        self.assertEqual(self.c.MAX_REQUEST,16384);self.assertEqual(self.c.MAX_RESPONSE,65536);self.assertEqual(self.c.MAX_HELLO,4096)
    def test_signed_error_scope(self):
        hi=self.hello();r=self.c.make_request(self.p,self.cs,hi,self.intent())
        out=self.c.make_response(self.p,self.ks,hi,r,False,'REJECTED')
        self.err(lambda:self.c.check_response(self.p,self.kp,hi,r,out))
        self.err(lambda:self.c.check_response(self.p,self.kp,self.hello(challenge=h('other')),r,out))
    def test_error_cannot_leak_traceback(self):self.err(lambda:self.c.make_response(self.p,self.ks,self.hello(),b'r',False,'/home/private/secret'))
    def test_bounded_decoder(self):self.err(lambda:self.c.load(b'x'*(self.c.MAX_REQUEST+1),self.c.MAX_REQUEST))
    def test_request_signature_cannot_be_an_intent_signature(self):
        i=self.intent();self.err(lambda:self.c.check_request(self.p,self.kp,self.store,self.cp,1,self.hello(),i))
