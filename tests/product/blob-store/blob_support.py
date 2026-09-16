"""Synthetic keys and data only; no user files or online dependencies."""
import importlib, tempfile, unittest, hashlib, json, sqlite3
from pathlib import Path
from dataclasses import replace
from auth_store_support import AuthStoreTest, Scenario, provider, epoch_bundle, h, control_id
from par_wire.codec import encode, decode
from par_crypto import objects
from par_crypto.errors import CryptoError
from par_crypto.primitives import hashed
from par_store.errors import StoreError
from par_auth.errors import AuthError
from par_auth_store import AuthorityStore, AuthenticatedWriter

class BlobTest(AuthStoreTest):
    def setUp(self):
        super().setUp()
        try:self.blob=importlib.import_module('par_blob_store')
        except ModuleNotFoundError:self.blob=None
        self.assertTrue(self.blob is not None and hasattr(self.blob,'BlobStore'), 'typed Blob/Store adapter is not implemented')
    def start(self,stage='active'):
        self.db=self.blob.BlobStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True)
        self.db.enroll(self.s.app,self.s.space,self.s.genesis)
        if stage=='enrolled':return self.db
        self.db.observe(self.s.space,self.b['raw'])
        if stage=='control':return self.db
        self.db.provide_membership(self.s.space,self.b['pages'])
        if stage=='membership':return self.db
        self.activate();return self.db
    def writer(self,index=0,secret=None,observer=None):
        d=self.s.devices[index]
        return self.blob.BlobWriter(self.db,d['cert'],self.s.secret if secret is None else secret,d['seed'],h('local-secret'),observer=observer)
    def legacy_writer(self):
        d=self.s.devices[0]
        return AuthenticatedWriter(self.db,d['cert'],self.s.secret,d['seed'],h('local-secret'))
    def attachment(self,index=0,plain=b'synthetic attachment',secret=None,**updates):
        header={0:self.s.app,1:self.s.space,2:1,3:h('blob-object'),4:3,5:index,6:0,7:len(plain)}
        header.update(updates.get('header',{}))
        raw=objects.seal_block(self.p,self.s.secret if secret is None else secret,header,plain,(index+1).to_bytes(24,'big'))
        return self.blob.Attachment(objects.block_id(raw),encode(header),raw)
    def verify(self,a,secret=None):
        return self.blob.verify_attachment(self.p,self.s.secret if secret is None else secret,a,app=self.s.app,space=self.s.space,epoch=1)
    def reject(self,code,fn):
        with self.assertRaises((StoreError,AuthError,CryptoError)) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def reopen(self,**kw):
        self.close();self.db=self.blob.BlobStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True,**kw);return self.db
    def rehash_snapshot(self,root):
        from par_store.recovery import file_hash
        file=root/'SNAPSHOT.json';m=json.loads(file.read_text())
        for item in m['files']:
            item['size']=(root/item['path']).stat().st_size;item['sha256']=file_hash(root/item['path'])
        file.write_text(json.dumps(m))
