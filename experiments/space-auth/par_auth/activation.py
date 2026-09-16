"""Atomic in-memory activation after all local seed bytes pass cryptographic checks.

Seed content is deliberately opaque: validating bytes is NOT validating an
Automerge baseline, carryover semantics, or dependency closure. No key export.
"""
from dataclasses import dataclass,field
import hashlib
from par_wire.codec import decode
from par_wire.errors import WireError
from par_crypto.primitives import hashed
from par_crypto import objects
from .common import fixed,blob,crypto
from .membership import member_certificate
from .errors import AuthError

@dataclass(frozen=True)
class ActiveMaterial:
    epoch: int
    anchor_id: bytes
    recipient_id: bytes
    secret: bytes=field(repr=False)
    seeds: tuple[tuple[bytes,bytes],...]=field(repr=False)
    cut: tuple[bytes,...]=field(repr=False)

def _keys(value,expected):
    if type(value) is not dict or set(value)!=expected or any(type(k) is not int for k in value):raise AuthError('SCHEMA_INVALID')
def _uint(v,maximum=2**64-1):
    if type(v) is not int or not 0<=v<=maximum:raise AuthError('SCHEMA_INVALID')
def parse_seed_manifest(raw):
    blob(raw,65536)
    try:m=decode(raw,max_bytes=65536)
    except WireError:raise AuthError('SCHEMA_INVALID') from None
    _keys(m,set(range(7)))
    if type(m[0]) is not int or m[0]!=1 or type(m[1]) is not str:raise AuthError('SCHEMA_INVALID')
    fixed(m[2],32);_uint(m[3]);fixed(m[4],16)
    if type(m[5]) is not list or type(m[6]) is not list:raise AuthError('SCHEMA_INVALID')
    if len(m[5])>256 or len(m[6])>256:raise AuthError('RESOURCE_BLOCKED')
    previous=None;block_ids=set();total=0
    for item in m[5]:
        _keys(item,set(range(5)));fixed(item[0],32);fixed(item[1],32);_uint(item[2]);_uint(item[3],262144);fixed(item[4],32)
        if (previous is not None and item[0]<=previous) or item[1] in block_ids:raise AuthError('SEED_LAYOUT')
        previous=item[0];block_ids.add(item[1]);total+=item[3]
    if total>4194304:raise AuthError('RESOURCE_BLOCKED')
    for cid in m[6]:fixed(cid,32)
    if m[6]!=sorted(set(m[6])):raise AuthError('SEED_LAYOUT')
    return m

def verify_activation(state,certificate,recipient_secret,package,package_ids,manifest,seeds):
    current=state.membership;anchor=state.epoch_anchor;a=anchor.body
    cert=member_certificate(state._p,state.app_id,current,certificate)
    did=hashed('device-id',[state.app_id,cert[3]])
    if current.get(did).role not in (1,2):raise AuthError('NOT_AUTHORIZED')
    historical=state.membership_at(anchor.id)
    old=historical.get(did)
    if old is None or old.role not in (1,2) or old.certificate_id!=current.get(did).certificate_id:raise AuthError('CERTIFICATE_BINDING')
    fixed(recipient_secret,32)
    if crypto(state._p.dh_public,recipient_secret)!=cert[4]:raise AuthError('CRYPTO_INVALID')
    ctx={0:state.app_id,1:state.space_id,2:a[3],3:a[10],4:did,5:old.certificate_id,6:a[6]}
    secret=crypto(objects.open_package,state._p,recipient_secret,a[11],ctx,package,package_ids,a[8])
    blob(manifest,65536)
    if hashed('auth-local/seed-root',[manifest])!=a[9]:raise AuthError('SEED_ROOT')
    m=parse_seed_manifest(manifest)
    if any(m[k]!=v for k,v in ((1,state.app_id),(2,state.space_id),(3,a[3]),(4,a[10]))):raise AuthError('CONTEXT_MISMATCH')
    if type(seeds) is not dict or len(seeds)>256:raise AuthError('SEED_SET')
    # Own all references; bytes are immutable. Never take caller-supplied plaintext or ready flags.
    supplied=dict(seeds)
    if set(supplied)!={e[1] for e in m[5]}:raise AuthError('SEED_SET')
    plains=[]
    for e in m[5]:
        raw=supplied[e[1]];blob(raw,270336)
        if objects.block_id(raw)!=e[1]:raise AuthError('SEED_DIGEST')
        header={0:state.app_id,1:state.space_id,2:a[3],3:e[0],4:5,5:0,6:e[2],7:e[3]}
        plain=crypto(objects.open_block,state._p,secret,header,raw)
        if hashlib.sha256(plain).digest()!=e[4]:raise AuthError('SEED_PLAINTEXT')
        plains.append((e[0],plain))
    return ActiveMaterial(a[3],anchor.id,did,secret,tuple(plains),tuple(m[6]))
