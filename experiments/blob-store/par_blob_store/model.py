"""Immutable encrypted input and separate typed ID / raw locator identities."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
from par_crypto import objects
from par_wire.codec import encode, decode
from par_crypto.primitives import domain
from par_store.model import BLOCK_MAX, PreparedCommit
from par_auth_store.model import BoundWrite
from .errors import BlobStoreError as E

MAX_ATTACHMENTS=128
MAX_BATCH_BYTES=8*1024*1024
MAX_MANIFEST_BYTES=131072
BLOB_KIND=3

def sha(raw):return hashlib.sha256(raw).digest()

@dataclass(frozen=True)
class Attachment:
    typed_id: bytes
    header_bytes: bytes = field(repr=False)
    sealed_bytes: bytes = field(repr=False)

@dataclass(frozen=True)
class BlockBinding:
    typed_id: bytes
    locator: bytes
    app: str
    space: bytes
    epoch: int
    object_id: bytes
    kind: int
    index: int
    key_generation: int
    plain_size: int
    sealed_size: int
    header_bytes: bytes = field(repr=False)
    def descriptor(self):return [self.typed_id,self.header_bytes]
    def slot(self):return (self.object_id,self.kind,self.index,self.key_generation)

@dataclass(frozen=True)
class BlobWrite:
    bound: BoundWrite = field(repr=False)
    manifest: bytes = field(repr=False)
    _seal: bytes = field(repr=False,compare=False)
    @property
    def prepared(self):return self.bound.prepared

def inspect_attachment(a:Attachment)->BlockBinding:
    if type(a) is not Attachment or type(a.typed_id) is not bytes or len(a.typed_id)!=32 or type(a.header_bytes) is not bytes or type(a.sealed_bytes) is not bytes:
        raise E('BLOB_INPUT')
    if not 1<=len(a.sealed_bytes)<=BLOCK_MAX or not 1<=len(a.header_bytes)<=4096:raise E('BLOB_LIMIT')
    if objects.block_id(a.sealed_bytes)!=a.typed_id:raise E('BLOCK_ID_MISMATCH')
    outer=objects.parse('sealed-block',a.sealed_bytes, BLOCK_MAX)
    header=objects.parse('block-header',a.header_bytes,4096)
    if objects.block_header(header)!=a.header_bytes or outer[0]!=a.header_bytes:raise E('BLOCK_HEADER_MISMATCH')
    if header[4]!=BLOB_KIND:raise E('BLOCK_KIND')
    if len(outer[2])!=header[7]+16:raise E('BLOCK_LENGTH')
    return BlockBinding(a.typed_id,sha(a.sealed_bytes),header[0],header[1],header[2],header[3],header[4],header[5],header[6],header[7],len(a.sealed_bytes),a.header_bytes)

def verify_attachment(provider,secret,a,*,app,space,epoch):
    b=inspect_attachment(a)
    if (b.app,b.space,b.epoch)!=(app,space,epoch):raise E('BLOCK_CONTEXT_MISMATCH')
    objects.open_block(provider,secret,decode(a.header_bytes),a.sealed_bytes)
    return b

def inspect_batch(attachments,header,provider=None,secret=None):
    if type(attachments) is not tuple:raise E('BLOB_INPUT')
    if len(attachments)>MAX_ATTACHMENTS:raise E('BLOB_LIMIT')
    total=0;ids=set();slots=set();out=[]
    for a in attachments:
        b=inspect_attachment(a);total+=b.sealed_size
        if total>MAX_BATCH_BYTES:raise E('BLOB_LIMIT')
        if b.typed_id in ids or b.slot() in slots:raise E('DUPLICATE_ATTACHMENT')
        if (b.app,b.space,b.epoch)!=(header[0],header[1],header[2]):raise E('BLOCK_CONTEXT_MISMATCH')
        if provider is not None:verify_attachment(provider,secret,a,app=header[0],space=header[1],epoch=header[2])
        ids.add(b.typed_id);slots.add(b.slot());out.append(b)
    return tuple(out)

def from_prepared(p:PreparedCommit):
    header=decode(decode(p.envelope)[0]);objects.change_header(header)
    attachments=[]
    for raw in p.blocks:
        obj=objects.parse('sealed-block',raw,BLOCK_MAX)
        attachments.append(Attachment(objects.block_id(raw),obj[0],raw))
    return header,tuple(attachments),inspect_batch(tuple(attachments),header)

def manifest_body(p,bindings):
    header=decode(decode(p.envelope)[0])
    return encode({0:1,1:header[0],2:p.space_id,3:p.epoch,4:p.object_id,5:p.envelope_id,
                   6:[b.descriptor() for b in bindings]},max_bytes=MAX_MANIFEST_BYTES)

def sign_manifest(provider,seed,p,bindings):
    body=manifest_body(p,bindings)
    sig=provider.sign(seed,domain('blob-store-local/attachment-sign',[body]))
    return encode({0:body,1:sig},max_bytes=MAX_MANIFEST_BYTES)

def verify_manifest(provider,public,p,bindings,raw):
    if type(raw) is not bytes or not 1<=len(raw)<=MAX_MANIFEST_BYTES:raise E('ATTACHMENT_MANIFEST')
    try:
        obj=decode(raw,max_bytes=MAX_MANIFEST_BYTES)
        if type(obj) is not dict or set(obj)!={0,1} or any(type(k) is not int for k in obj):raise ValueError()
        if obj[0]!=manifest_body(p,bindings):raise ValueError()
    except Exception:raise E('ATTACHMENT_MANIFEST') from None
    provider.verify(public,domain('blob-store-local/attachment-sign',[obj[0]]),obj[1])
