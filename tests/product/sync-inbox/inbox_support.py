"""Public opaque inner bytes. Actual Ed25519, AEAD and AuthorityStore are used."""
import importlib.util, copy, hashlib
from auth_store_support import AuthStoreTest, h
from par_crypto import objects
from par_wire.codec import decode

class InboxTest(AuthStoreTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp04.inbox'), 'durable sync inbox not implemented')
        from product.wp04.inbox import SyncInbox, InboxError
        self.cls=SyncInbox;self.error=InboxError;self.start();self.box=None
        self.scope=dict(app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'))
        self.path=self.root.parent/'inbox';self.addCleanup(self.close_box)
    def close_box(self):
        if self.box:self.box.close();self.box=None
    def create(self,**kw):
        self.box=self.cls.create(self.path,self.db,**self.scope,**kw);return self.box
    def reopen_box(self,**kw):
        self.close_box();self.box=self.cls.open(self.path,self.db,**self.scope,**kw);return self.box
    def change(self,label='a',*,parents=(),previous=None,seq=1,index=0,header_patch=None,payload=None):
        _,head,_,_=self.request(index=index,sequence=seq,previous=previous)
        body=payload or (b'OPAQUE-CONTRACT-NOT-AUTOMERGE:'+label.encode())
        head[10]=list(parents);head[12]=h('inner:'+label);head[11]=len(body)
        if header_patch:head.update(header_patch)
        raw=objects.seal_change(self.p,self.s.secret,self.s.devices[index]['seed'],head,body,h('nonce:'+label)[:24])
        return raw,self.s.devices[index]['cert']
    def eid(self,raw):return objects.envelope_id(raw)
    def cid(self,raw):return decode(decode(raw)[0])[12]
    def receive(self,pair):return self.box.receive(*pair)
    def bad(self,code,fn):
        with self.assertRaises(self.error) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
