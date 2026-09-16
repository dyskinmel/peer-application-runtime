"""Only deterministic public test material; no user keys or network calls."""
import importlib,unittest
from pathlib import Path
from dataclasses import replace
from auth_support import h,provider
from recovery_support import RecoveryTest
from par_wire.codec import encode,decode

def require(test):
    try:m=importlib.import_module('par_keeper')
    except ModuleNotFoundError:m=None
    test.assertTrue(m is not None and hasattr(m,'Authority'),'Keeper contracts are not implemented')
    return m
class ContractTest(unittest.TestCase):
    def setUp(self):
        self.k=require(self);self.p=provider();self.owner=h('keeper-owner');self.seed=h('keeper-signing');self.subject=h('keeper-caller')
        self.pk=self.p.sign_public(self.seed);self.sp=self.p.sign_public(self.subject)
        self.a=self.k.Authority('org.example.keeper',h('space'),h('head'),3,2,self.p.sign_public(self.owner))
        self.index=h('index')
    def cap(self,**kw):
        return self.k.issue_capability(self.p,self.owner,kw.pop('authority',self.a),kw.pop('keeper',self.pk),kw.pop('subject',self.sp),kw.pop('index',self.index),kw.pop('methods',('reserve','put','seal','get','receipt','status','challenge','renew','release')),kw.pop('maximum_seconds',60),kw.pop('nonce',h('cap-nonce')),**kw)
    def err(self,code,fn):
        with self.assertRaises(self.k.KeeperError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
class FakeClock:
    def __init__(self,k):self.k=k;self.boot=h('boot-a');self.ns=10_000_000_000
    def sample(self):return self.k.Tick(self.boot,self.ns)
class KeeperTest(RecoveryTest):
    def setUp(self):
        super().setUp();self.k=require(self);self.bundle=self.collect();self.rpin=self.pin(self.bundle)
        self.ks=h('keeper-signing');self.kp=self.p.sign_public(self.ks);self.cs=self.reader['seed'];self.cp=self.p.sign_public(self.cs)
        self.authority=self.k.Authority(self.s.app,self.s.space,self.rpin.head,1,1,self.p.sign_public(self.s.owner))
        self.clock=FakeClock(self.k);self.path=Path(self.tmp.name)/'keeper';self.keeper=None;self.counter=0
        self.total=len(self.bundle.index)+sum(map(len,self.bundle.objects.values()))
        self.cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,tuple(self.k.METHODS),60,h('cap-nonce'))
    def tearDown(self):
        if self.keeper is not None:self.keeper.close()
        super().tearDown()
    def open_keeper(self,**kw):
        self.assertTrue(hasattr(self.k,'Keeper'),'Keeper service is not implemented')
        self.keeper=self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=kw.pop('quota_bytes',self.total*3),clock=self.clock,allow_unpatched_sqlite=True,**kw);return self.keeper
    def call(self,action,lease=None,payload=None,*,cap=None,seed=None,nonce=None):
        self.counter+=1
        return self.k.make_call(self.p,seed or self.cs,cap or self.cap,action,lease,nonce or h('call-'+str(self.counter)),payload)
    def reserve(self,nonce=None,**kw):
        ttl=kw.pop('seconds',30);g=kw.pop('cap',self.cap)
        c=self.call('reserve',payload=self.k.reserve_payload(self.bundle.index,self.rpin,ttl),cap=g,nonce=nonce)
        self.rescall=c
        return self.keeper.reserve(self.bundle.index,self.rpin,ttl,g,c)
    def put(self,lid,oid,raw=None,**kw):
        raw=self.bundle.objects[oid] if raw is None else raw;g=kw.pop('cap',self.cap)
        return self.keeper.put(lid,oid,raw,g,self.call('put',lid,self.k.put_payload(oid,raw),cap=g,**kw))
    def fill(self,lid):
        for oid in self.bundle.objects:self.put(lid,oid)
    def seal(self,lid,nonce=None):
        self.sealcall=self.call('seal',lid,nonce=nonce);return self.keeper.seal(lid,self.cap,self.sealcall)
    def ready(self,**kw):
        self.open_keeper(**kw);lid=self.reserve();self.fill(lid);rc=self.seal(lid);return lid,rc
    def get(self,lid,oid,cap=None):
        g=cap or self.cap;return self.keeper.fetch(lid,oid,g,self.call('get',lid,oid,cap=g))
    def status(self,lid):return self.keeper.status(lid,self.cap,self.call('status',lid))
    def renew(self,lid,seconds=30,nonce=None):
        self.renewcall=self.call('renew',lid,seconds,nonce=nonce);return self.keeper.renew(lid,seconds,self.cap,self.renewcall)
    def release(self,lid,nonce=None):
        self.releasecall=self.call('release',lid,nonce=nonce);return self.keeper.release(lid,self.cap,self.releasecall)
    def err(self,code,fn):
        with self.assertRaises(Exception) as cm:fn()
        self.assertTrue(hasattr(cm.exception,'code'),repr(cm.exception))
        if code:self.assertEqual(cm.exception.code,code)
