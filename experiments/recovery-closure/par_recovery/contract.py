"""Bounded signed index candidate. Pin MUST arrive through a separate trusted channel.

Object IDs are local transfer identities, NOT PAR envelope/block identifiers.
No claim of minimum CRDT closure or freshness beyond the supplied head is made.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from par_wire.codec import encode,decode
from par_crypto.primitives import hashed,domain
from par_crypto import objects
from .errors import RecoveryError as E
MAX_INDEX=524288
MAX_OBJECT=900000
MAX_BYTES=32*1024*1024
MAX_OBJECTS=1024
MAX_ENVELOPES=64
KINDS={'replay','certificate','grant','package','seed-manifest','seed','envelope','attachment','block'}
@dataclass(frozen=True)
class Pin:
    app: str
    space: bytes
    head: bytes
    sequence: int
    epoch: int
    recipient_id: bytes
    certificate_id: bytes
    roots: tuple[bytes,...]
    index_id: bytes
@dataclass(frozen=True)
class Grant:
    certificate: bytes=field(repr=False)
    package: bytes=field(repr=False)
    package_ids: tuple[bytes,...]
    seed_manifest: bytes=field(repr=False)
    seeds: tuple[tuple[bytes,bytes],...]=field(repr=False)
@dataclass(frozen=True)
class Bundle:
    index: bytes
    objects: dict[bytes,bytes]=field(repr=False)
def fixed(x,n=32):
    if type(x) is not bytes or len(x)!=n:raise E('INDEX_SCHEMA')
def integer(x,lo=0,hi=2**64-1):
    if type(x) is not int or not lo<=x<=hi:raise E('INDEX_SCHEMA')
def keys(x,ks):
    if type(x) is not dict or any(type(k) is not int for k in x) or set(x)!=set(ks):raise E('INDEX_SCHEMA')
def bounded(raw,limit=MAX_OBJECT):
    if type(raw) is not bytes or not 1<=len(raw)<=limit:raise E('OBJECT_LIMIT')
def dumps(value,limit=MAX_INDEX):return encode(value,max_bytes=limit)
def loads(raw,limit=MAX_INDEX):
    try:
        bounded(raw,limit);v=decode(raw,max_bytes=limit)
        if dumps(v,limit)!=raw:raise E('INDEX_SCHEMA')
        return v
    except Exception:raise E('INDEX_SCHEMA') from None
def object_id(kind,raw):
    if kind not in KINDS:raise E('INDEX_SCHEMA')
    bounded(raw);return hashed('recovery-local/object',[kind,raw])
def index_id(raw):
    bounded(raw,MAX_INDEX);return hashed('recovery-local/index',[raw])
def sign_index(provider,seed,body):
    raw=dumps(body)
    return dumps({0:raw,1:provider.sign(seed,domain('recovery-local/index-sign',[raw]))})
def ordered_ids(v,maximum=MAX_OBJECTS,nonempty=False):
    if type(v) is not list or len(v)>maximum or (nonempty and not v):raise E('INDEX_SCHEMA')
    for x in v:fixed(x)
    if v!=sorted(set(v)):raise E('INDEX_SCHEMA')
def inspect_index(raw,pin):
    """Structural admission only; signature needs the received authenticated replay."""
    try:
        o=loads(raw);keys(o,{0,1});bounded(o[0],MAX_INDEX);fixed(o[1],64)
        v=loads(o[0]);keys(v,range(16))
        integer(v[0],1,1)
        if v[1]!='recovery-closure-local':raise E('INDEX_SCHEMA')
        objects.app_id(v[2])
        for i in (3,4,7,8,10,11,12,13):fixed(v[i])
        integer(v[5],1);integer(v[6],1);ordered_ids(v[9],MAX_ENVELOPES,True)
        if type(v[14]) is not list or not 1<=len(v[14])<=MAX_ENVELOPES:raise E('INDEX_SCHEMA')
        ids=[]
        for e in v[14]:
            keys(e,range(5));fixed(e[0]);fixed(e[1]);fixed(e[2]);ids.append(e[0])
            if e[3] is not None:fixed(e[3])
            if type(e[4]) is not list or len(e[4])>128:raise E('INDEX_SCHEMA')
            for i in e[4]:fixed(i)
            if len(set(e[4]))!=len(e[4]) or (e[3] is None and e[4]):raise E('INDEX_SCHEMA')
        if ids!=sorted(set(ids)) or not set(v[9])<=set(ids):raise E('INDEX_SCHEMA')
        if type(v[15]) is not list or not 1<=len(v[15])<=MAX_OBJECTS:raise E('INDEX_SCHEMA')
        ids=[];size=0
        for d in v[15]:
            if type(d) is not list or len(d)!=3:raise E('INDEX_SCHEMA')
            fixed(d[0]);ids.append(d[0]);integer(d[2],1,MAX_OBJECT)
            if type(d[1]) is not str or d[1] not in KINDS:raise E('INDEX_SCHEMA')
            size+=d[2]
        if ids!=sorted(set(ids)) or size>MAX_BYTES:raise E('INDEX_SCHEMA')
    except E:raise
    except Exception:raise E('INDEX_SCHEMA') from None
    if type(pin) is not Pin:raise E('PIN_MISMATCH')
    if (type(pin.sequence) is not int or type(pin.epoch) is not int or type(pin.roots) is not tuple or
        (v[2],v[3],v[4],v[5],v[6],v[7],v[8],tuple(v[9]),index_id(raw)) !=
        (pin.app,pin.space,pin.head,pin.sequence,pin.epoch,pin.recipient_id,pin.certificate_id,pin.roots,pin.index_id)):
        raise E('PIN_MISMATCH')
    return v,o
