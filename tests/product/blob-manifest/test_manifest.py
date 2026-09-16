"""Manifest tests must fail if whole-file layout or metadata validation is weakened."""
import importlib, unittest
from par_wire.codec import encode,decode
from par_blob_store import Attachment,inspect_attachment
from par_crypto import objects
from blob_support import BlobTest,h

class ManifestTests(BlobTest):
    def setUp(self):
        super().setUp()
        try:self.file=importlib.import_module('par_file')
        except ModuleNotFoundError:self.file=None
        self.assertIsNotNone(self.file,'whole-file manifest adapter not implemented')
        self.m=self.file.manifest
    def sample(self):
        a=self.attachment(0,plain=b'abc',header={3:h('file')})
        return {0:1,1:'file-manifest-local',2:self.s.app,3:self.s.space,4:1,5:h('file'),6:0,7:3,8:262144,9:__import__('hashlib').sha256(b'abc').digest(),10:'資料.txt',11:'text/plain',12:[[a.typed_id,a.header_bytes]]}
    def bad(self,v):
        with self.assertRaises(self.file.FileError):self.m.loads(self.m.dumps(v))
    def test_roundtrip(self):
        v=self.sample();self.assertEqual(self.m.loads(self.m.dumps(v)),v)
    def test_empty_file(self):
        v=self.sample();v[7]=0;v[9]=__import__('hashlib').sha256(b'').digest();v[12]=[];self.assertEqual(self.m.loads(self.m.dumps(v)),v)
    def test_manifest_has_distinct_object_domain(self):self.assertNotEqual(self.m.manifest_object(h('file')),h('file'))
    def test_noncanonical_cbor(self):
        with self.assertRaises(self.file.FileError):self.m.loads(b'\xbf\xff')
    def test_trailing_bytes(self):
        with self.assertRaises(self.file.FileError):self.m.loads(encode(self.sample())+b'\x00')
    def test_metadata_size_budget(self):
        with self.assertRaises(self.file.FileError):self.m.loads(b'\x00'*32769)
    def test_valid_multichunk_layout(self):
        v=self.sample();v[7]=262145;v[12]=[]
        for i,data in enumerate((b'a'*262144,b'b')):
            a=self.attachment(i,plain=data,header={3:h('file')});v[12].append([a.typed_id,a.header_bytes])
        self.assertEqual(self.m.loads(self.m.dumps(v)),v)
    def test_reordered_chunks(self):
        v=self.sample();a=self.attachment(1,plain=b'b',header={3:h('file')});v[7]=262145;v[12]=[[a.typed_id,a.header_bytes],v[12][0]];self.bad(v)
    def test_duplicate_chunk(self):
        v=self.sample();v[7]=262145;v[12]*=2;self.bad(v)
    def test_missing_chunk(self):v=self.sample();v[12]=[];self.bad(v)
    def test_extra_chunk(self):v=self.sample();v[7]=0;self.bad(v)
    def test_wrong_total_size(self):v=self.sample();v[7]=4;self.bad(v)
    def test_empty_digest_fixed(self):
        v=self.sample();v[7]=0;v[12]=[];self.bad(v)

for name,key,value in [
 ('version',0,2),('magic',1,'attachment-sidecar'),('app',2,'COM.bad'),('space',3,b'x'),
 ('epoch_bool',4,True),('negative_epoch',4,-1),('epoch_overflow',4,2**64),('file_id',5,b'x'),
 ('generation',6,-1),('size_negative',7,-1),('size_bool',7,True),('size_limit',7,7*1024*1024+1),
 ('chunk_size',8,1024),('digest',9,b'x'),('name_empty',10,''),('name_long',10,'界'*100),
 ('name_null',10,'bad\x00name'),('name_slash',10,'a/b'),('name_backslash',10,'a\\b'),('name_parent',10,'..'),
 ('name_control',10,'a\nb'),('mime',11,'notmime'),('mime_long',11,'x/'+('a'*127)),('mime_type',11,0),
 ('descriptor_type',12,{}),('descriptor_bad',12,[[b'1',b'2']]),
]:
    def test(self,key=key,value=value):v=self.sample();v[key]=value;self.bad(v)
    setattr(ManifestTests,'test_reject_'+name,test)
for key,value in [(0,'other.app'),(1,b'x'*32),(2,2),(3,b'x'*32),(4,1),(5,1),(6,1),(7,4)]:
    def test(self,key=key,value=value):
        v=self.sample();head=decode(v[12][0][1]);head[key]=value;v[12][0][1]=encode(head);self.bad(v)
    setattr(ManifestTests,'test_chunk_header_mismatch_'+str(key),test)
for name,mut in [('extra_key',lambda v:v.update({13:0})),('missing_key',lambda v:v.pop(9)),('float_key',lambda v:v.update({13.1:0}))]:
    def test(self,mut=mut):
        v=self.sample();mut(v)
        with self.assertRaises(Exception):self.m.dumps(v)
    setattr(ManifestTests,'test_'+name,test)
