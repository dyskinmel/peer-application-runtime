"""Public synthetic fixtures for the auth/Store candidate only."""
import hashlib, importlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from auth_support import Scenario, provider, epoch_bundle, h, control_id, pages_for, member_root
from par_wire.codec import encode, decode
from par_crypto import objects
from par_crypto.primitives import hashed
from par_store.errors import StoreError
from par_auth.errors import AuthError
ROOT=Path(__file__).resolve().parents[3]

class AuthStoreTest(unittest.TestCase):
    def setUp(self):
        try:self.m=importlib.import_module('par_auth_store')
        except ModuleNotFoundError:self.m=None
        self.assertTrue(self.m is not None and hasattr(self.m,'AuthorityStore'), 'atomic authority/Store adapter has not been implemented')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'db';self.p=provider();self.s=Scenario(self.p);self.b=epoch_bundle(self.s)
        self.db=None;self.addCleanup(self.close)
    def close(self):
        if self.db is not None:self.db.close();self.db=None
    def start(self,stage='active'):
        self.db=self.m.AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True)
        self.db.enroll(self.s.app,self.s.space,self.s.genesis)
        if stage=='enrolled':return self.db
        self.db.observe(self.s.space,self.b['raw'])
        if stage=='control':return self.db
        self.db.provide_membership(self.s.space,self.b['pages'])
        if stage=='membership':return self.db
        self.activate();return self.db
    def activate(self,b=None,index=0):
        b=b or self.b;d=self.s.devices[index]
        return self.db.activate(self.s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
    def writer(self,index=0,secret=None,observer=None):
        d=self.s.devices[index]
        return self.m.AuthenticatedWriter(self.db,d['cert'],self.s.secret if secret is None else secret,d['seed'],h('local-secret'),observer=observer)
    def request(self,op=1,index=0,b=None,sequence=1,previous=None):
        b=b or self.b;payload=b'opaque inner change - not an Automerge document';cache=b'candidate materialization not semantically checked'
        hdr={0:self.s.app,1:self.s.space,2:b['body'][3],3:h('doc'),4:1,5:self.s.devices[index]['id'],6:h('actor-generation')[:16],7:sequence,8:previous,9:h('schema'),10:[],11:len(payload),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
        return op.to_bytes(16,'big'),hdr,payload,cache
    def same_epoch(self):
        raw=self.s.raw(self.s.next(self.b['raw']))
        self.db.observe(self.s.space,raw);self.db.provide_membership(self.s.space,self.b['pages']);return raw
    def next_epoch(self,entries=None,secret=None):
        b=epoch_bundle(self.s,self.s.next(self.b['raw'],3),secret or h('content-next'),entries=entries)
        self.db.observe(self.s.space,b['raw']);self.db.provide_membership(self.s.space,b['pages']);return b
    def reject(self,code,fn):
        with self.assertRaises((StoreError,AuthError)) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def count(self,table):return self.db._storage.connection.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def reopen(self,**kw):
        self.close();self.db=self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True,**kw);return self.db
