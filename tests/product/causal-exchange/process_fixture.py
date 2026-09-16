"""Public test keys and opaque inner bytes; not a CRDT or production provisioner."""
from pathlib import Path
from auth_support import Scenario,provider,epoch_bundle,h,control_id
from par_auth_store import AuthorityStore
from par_crypto import objects
from product.wp04.inbox import SyncInbox
from product.wp04.exchange import Source

class Peer:
    def __init__(self, root, *, expected_pin=None):
        root=Path(root);root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.p=provider();self.s=Scenario(self.p);self.b=epoch_bundle(self.s)
        if (root/'db').exists():
            self.db=AuthorityStore.open(root/'db',provider=self.p,allow_unpatched_sqlite=True)
        else:
            self.db=AuthorityStore.create(root/'db',provider=self.p,allow_unpatched_sqlite=True)
            self.db.enroll(self.s.app,self.s.space,self.s.genesis)
            self.db.observe(self.s.space,self.b['raw']);self.db.provide_membership(self.s.space,self.b['pages'])
        d=self.s.devices[0]
        self.db.activate(self.s.space,d['cert'],d['secret'],self.b['packages'][d['id']],self.b['ids'],self.b['manifest'],self.b['seeds'])
        self.scope=dict(app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'))
        fn=SyncInbox.open if (root/'inbox').exists() else SyncInbox.create
        kwargs={'expected_pin':expected_pin} if fn==SyncInbox.open and expected_pin is not None else {}
        self.box=fn(root/'inbox',self.db,**self.scope,**kwargs)
        self.source=Source(self.box,d['cert'],d['seed'])
    def change(self,label,seq=1,parents=(),previous=None):
        d=self.s.devices[0];plain=b'PUBLIC OPAQUE INPUT, NOT AUTOMERGE: '+label.encode()
        head={0:self.s.app,1:self.s.space,2:1,3:h('doc'),4:1,5:d['id'],6:h('actor-generation')[:16],7:seq,8:previous,9:h('schema'),10:list(parents),11:len(plain),12:h('inner:'+label),13:control_id(self.b['raw']),14:1,15:0}
        return objects.seal_change(self.p,self.s.secret,d['seed'],head,plain,h('nonce:'+label)[:24]),d['cert']
    def chain(self):
        a=self.change('a');b=self.change('b',2,[h('inner:a')],objects.envelope_id(a[0]));return a,b
    def close(self):
        self.box.close();self.db.close()
