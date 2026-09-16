"""Public synthetic inner changes; real signatures, AEAD and SQLite."""
import copy, importlib.util, types
from auth_store_support import AuthStoreTest,h
from auth_support import epoch_bundle,pages_for,member_root
from par_crypto import objects
from par_crypto.primitives import hashed
from par_wire.codec import encode
from product.wp04 import contracts as c

class MaterializationDouble:
    def __init__(self):
        self.identity={'name':'@automerge/automerge','version':'3.4.1','kind':'contract-test-double','digest':'d'*64}
        self.calls=0;self.hook=None;self.mutate=None
    def materialize(self,request):
        self.calls+=1
        if self.hook:self.hook()
        ds=request['changes']; hashes={x['hash'] for x in ds};deps={v for x in ds for v in x['dependencies']}
        r={'profile':'par-document-apply-local-0035','requestDigest':c.request_digest(request),
           'engine':dict(self.identity),'schema':'note-v1-local','appliedHashes':sorted(hashes),
           'heads':sorted(hashes-deps),'missing':[],
           'changes':[{k:x[k] for k in ('actor','sequence','hash','dependencies')} for x in ds],
           'note':{'title':'synthetic materialization','body':'SYNTHETIC-NOT-A-CRDT:'+','.join(sorted(hashes)),'titleConflicts':[]}}
        if self.mutate:self.mutate(r)
        return r

class ApplyTest(AuthStoreTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp04.application'), 'durable document application is not implemented')
        from product.wp04.application import ApplicationStore,DocumentApplier
        self.Store=ApplicationStore;self.Applier=DocumentApplier
        old=self.m;self.m=types.SimpleNamespace(AuthorityStore=ApplicationStore,AuthenticatedWriter=old.AuthenticatedWriter)
        # A second editor is explicit in the signed genesis/epoch, not a bypass.
        self.s.devices[1]['role']=2
        self.s.entries=[{0:d['id'],1:d['cid'],2:d['role']} for d in self.s.devices]
        self.s.pages=pages_for(self.s.entries);self.s.root=member_root(self.s.pages)
        genesis={0:1,1:self.s.app,2:self.p.sign_public(self.s.owner),3:h('genesis-salt'),4:self.s.root,5:self.s.policy}
        self.s.genesis=objects._signed(self.p,self.s.owner,'genesis-sign',genesis)
        self.s.space=hashed('space-id',[encode(genesis)])
        self.s.initial.update({1:self.s.space,4:self.s.space,6:self.s.root})
        self.b=epoch_bundle(self.s)
        self.start();self.port=MaterializationDouble();self.a=self.make()
    def make(self,**overrides):
        opts={'app_id':self.s.app,'space_id':self.s.space,'document_id':h('doc'),'epoch':1,'schema_id':h('schema'),'allow_contract_double':True}
        opts.update(overrides)
        return self.Applier(self.db,self.port,self.s.devices[0]['cert'],h('local-apply-secret'),**opts)
    def saved(self,op=1,index=0,sequence=1,previous=None,deps=()):
        o,hdr,p,cache=self.request(op=op,index=index,sequence=sequence,previous=previous)
        hdr[12]=h('apply-change-'+str(op));hdr[10]=list(deps)
        result=self.writer(index=index).write(o,hdr,p,cache)
        return result.envelope_id,hdr[12]
    def call(self,targets,op=10,expected=0):return self.a.apply(op.to_bytes(16,'big'),tuple(targets),expected_revision=expected)
    def deny(self,code,fn):
        with self.assertRaises(Exception) as cm:fn()
        if code:self.assertEqual(getattr(cm.exception,'code',None),code)
    def nums(self):
        c=self.db._storage.connection
        return {n:c.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in ['document_inputs','document_apply_events','document_frontiers','document_apply_nonces']}
