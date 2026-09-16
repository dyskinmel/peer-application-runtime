"""Bounded, encrypted-at-rest whole-file manifest candidate (not a wire freeze)."""
from __future__ import annotations
import hashlib,re
from par_wire.codec import encode,decode
from par_crypto import objects
from par_crypto.primitives import hashed
from .errors import FileError as E

CHUNK_BYTES=262144
MAX_FILE_BYTES=7*1024*1024   # Existing 8 MiB BlobStore batch leaves room for headers/manifest.
MAX_MANIFEST_BYTES=32768
MAX_CHUNKS=MAX_FILE_BYTES//CHUNK_BYTES

def manifest_object(file_id: bytes) -> bytes:
    if type(file_id) is not bytes or len(file_id)!=32:raise E('FILE_MANIFEST_INVALID')
    return hashed('file-local/manifest-object',[file_id])

def metadata(name: str, mime: str) -> None:
    if type(name) is not str or not name or name in ('.','..') or any(ord(c)<32 or ord(c)==127 or c in '/\\' for c in name):
        raise E('FILE_METADATA_INVALID')
    try:n=len(name.encode('utf-8'))
    except UnicodeError:raise E('FILE_METADATA_INVALID') from None
    if n>255:raise E('FILE_METADATA_INVALID')
    if type(mime) is not str or len(mime)>127 or not re.fullmatch(r'[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+',mime):
        raise E('FILE_METADATA_INVALID')

def _validate(v: dict) -> dict:
    if type(v) is not dict or set(v)!=set(range(13)) or any(type(k) is not int for k in v):raise E('FILE_MANIFEST_INVALID')
    if type(v[0]) is not int or v[0]!=1 or v[1]!='file-manifest-local':raise E('FILE_MANIFEST_INVALID')
    objects.app_id(v[2])
    for k in (3,5,9):
        if type(v[k]) is not bytes or len(v[k])!=32:raise E('FILE_MANIFEST_INVALID')
    for k in (4,6,7,8):
        if type(v[k]) is not int or not 0<=v[k]<2**64:raise E('FILE_MANIFEST_INVALID')
    if v[7]>MAX_FILE_BYTES or v[8]!=CHUNK_BYTES:raise E('FILE_LIMIT')
    metadata(v[10],v[11])
    count=(v[7]+CHUNK_BYTES-1)//CHUNK_BYTES
    if type(v[12]) is not list or len(v[12])!=count:raise E('FILE_CHUNK_SET')
    if count==0 and v[9]!=hashlib.sha256(b'').digest():raise E('FILE_HASH_MISMATCH')
    ids=set()
    for i,pair in enumerate(v[12]):
        if type(pair) is not list or len(pair)!=2 or type(pair[0]) is not bytes or len(pair[0])!=32 or type(pair[1]) is not bytes or len(pair[1])>4096:
            raise E('FILE_CHUNK_SET')
        if pair[0] in ids:raise E('FILE_CHUNK_SET')
        ids.add(pair[0])
        h=objects.parse('block-header',pair[1],4096)
        expected={0:v[2],1:v[3],2:v[4],3:v[5],4:3,5:i,6:v[6],7:min(CHUNK_BYTES,v[7]-i*CHUNK_BYTES)}
        if objects.block_header(h)!=pair[1] or h!=expected:raise E('FILE_CHUNK_CONTEXT')
    return v

def dumps(value: dict) -> bytes:
    try:
        _validate(value)
        return encode(value,max_bytes=MAX_MANIFEST_BYTES)
    except E:raise
    except Exception:raise E('FILE_MANIFEST_INVALID') from None

def loads(raw: bytes) -> dict:
    try:
        if type(raw) is not bytes or not 1<=len(raw)<=MAX_MANIFEST_BYTES:raise E('FILE_LIMIT')
        v=decode(raw,max_bytes=MAX_MANIFEST_BYTES)
        _validate(v)
        if dumps(v)!=raw:raise E('FILE_MANIFEST_INVALID')
        return v
    except E:raise
    except Exception:raise E('FILE_MANIFEST_INVALID') from None

def root_header(value: dict, plain_size: int) -> dict:
    return {0:value[2],1:value[3],2:value[4],3:manifest_object(value[5]),4:3,5:0,6:value[6],7:plain_size}

def open_manifest(provider,secret,attachment,*,app,space,epoch) -> dict:
    from par_blob_store import inspect_attachment
    try:
        b=inspect_attachment(attachment)
        if (b.app,b.space,b.epoch)!=(app,space,epoch) or b.plain_size>MAX_MANIFEST_BYTES:raise E('FILE_CONTEXT_MISMATCH')
        raw=objects.open_block(provider,secret,decode(b.header_bytes),attachment.sealed_bytes)
        v=loads(raw)
        if (v[2],v[3],v[4])!=(app,space,epoch) or b.header_bytes!=objects.block_header(root_header(v,len(raw))):
            raise E('FILE_CONTEXT_MISMATCH')
        return v
    except E:raise
    except Exception:raise E('FILE_MANIFEST_INVALID') from None

def check_bindings(value: dict, bindings) -> None:
    """Exact order/set check, not counts alone. Input has already passed loads()."""
    if [b.descriptor() for b in bindings]!=value[12]:raise E('FILE_CHUNK_SET')
