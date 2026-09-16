"""Strict non-delegating capability and possession proof for local callable I/O.

Known authority is supplied by a trusted host, not inferred from these envelopes.
All formats here are candidate overlays, not approved network protocol messages.
"""
from __future__ import annotations
from dataclasses import dataclass
from par_wire.codec import encode,decode
from par_crypto.primitives import hashed,domain
from par_crypto.objects import app_id
from par_recovery.contract import Pin,inspect_index,index_id
from .errors import KeeperError as E

PROFILE='keeper-retention-local'
METHODS=frozenset(('reserve','put','seal','get','receipt','status','challenge','renew','release'))
MAX_SECONDS=86400
MAX_CONTRACT=16384
I64=2**63-1
@dataclass(frozen=True)
class Authority:
    app:str
    space:bytes
    head:bytes
    sequence:int
    epoch:int
    issuer:bytes

def fixed(v,n=32):
    if type(v) is not bytes or len(v)!=n:raise E('CONTRACT_SCHEMA')
def integer(v,lo=0,hi=I64):
    if type(v) is not int or not lo<=v<=hi:raise E('CONTRACT_SCHEMA')
def keys(v,expected):
    if type(v) is not dict or any(type(k) is not int for k in v) or set(v)!=set(expected):raise E('CONTRACT_SCHEMA')
def dump(v):
    try:return encode(v,max_bytes=MAX_CONTRACT)
    except Exception:raise E('CONTRACT_SCHEMA') from None

def load(raw):
    try:
        if type(raw) is not bytes or not 1<=len(raw)<=MAX_CONTRACT:raise ValueError()
        v=decode(raw,max_bytes=MAX_CONTRACT)
        if dump(v)!=raw:raise ValueError()
        return v
    except Exception:raise E('CONTRACT_SCHEMA') from None

def authority_body(a):
    if type(a) is not Authority:raise E('CONTRACT_SCHEMA')
    try:app_id(a.app)
    except Exception:raise E('CONTRACT_SCHEMA') from None
    for v in (a.space,a.head,a.issuer):fixed(v)
    integer(a.sequence,1);integer(a.epoch,1)
    return [a.app,a.space,a.head,a.sequence,a.epoch,a.issuer]

def authority_from(v):
    if type(v) is not list or len(v)!=6:raise E('CONTRACT_SCHEMA')
    a=Authority(*v);authority_body(a);return a

def signed(provider,seed,label,body):
    b=dump(body);return dump({0:b,1:provider.sign(seed,domain('keeper-local/'+label,[b]))})
def split(raw):
    o=load(raw);keys(o,(0,1));fixed(o[1],64);v=load(o[0]);return v,o

def capability_id(raw):return hashed('keeper-local/capability-id',[raw])
def capability_shape(v):
    keys(v,range(9));integer(v[0],1,1)
    if v[1]!=PROFILE:raise E('CONTRACT_SCHEMA')
    authority_from(v[2])
    for k in (3,4,5,8):fixed(v[k])
    ms=v[6]
    if type(ms) is not list or not ms or any(type(m) is not str or m not in METHODS for m in ms) or ms!=sorted(set(ms)):raise E('CONTRACT_SCHEMA')
    integer(v[7],1,MAX_SECONDS)

def issue_capability(provider,issuer_seed,authority,keeper,subject,index,methods,maximum_seconds,nonce):
    if type(methods) not in (tuple,list) or any(type(x) is not str for x in methods):raise E('CONTRACT_SCHEMA')
    if len(set(methods))!=len(methods):raise E('CONTRACT_SCHEMA')
    v={0:1,1:PROFILE,2:authority_body(authority),3:keeper,4:subject,5:index,6:sorted(methods),7:maximum_seconds,8:nonce}
    capability_shape(v)
    if provider.sign_public(issuer_seed)!=authority.issuer:raise E('CAPABILITY_AUTH')
    return signed(provider,issuer_seed,'capability-sign',v)

def verify_capability(provider,authority,keeper,raw):
    authority_body(authority);fixed(keeper);v,o=split(raw);capability_shape(v)
    try:provider.verify(authority.issuer,domain('keeper-local/capability-sign',[o[0]]),o[1])
    except Exception:raise E('CAPABILITY_AUTH') from None
    if v[2]!=authority_body(authority) or v[3]!=keeper:raise E('CAPABILITY_SCOPE')
    return v

def payload_id(action,payload):
    # Bound the canonical payload before passing it to the primitive encoder.
    return hashed('keeper-local/request-payload',[action,dump(payload)])
def call_shape(v):
    keys(v,range(9));integer(v[0],1,1)
    if v[1]!=PROFILE or type(v[5]) is not str or v[5] not in METHODS:raise E('CONTRACT_SCHEMA')
    for k in (2,3,4,7,8):fixed(v[k])
    if v[5]=='reserve':
        if v[6] is not None:raise E('CONTRACT_SCHEMA')
    else:fixed(v[6])

def make_call(provider,subject_seed,capability,action,lease_id,operation_id,payload=None):
    cap,_=split(capability);capability_shape(cap)
    pub=provider.sign_public(subject_seed)
    if pub!=cap[4]:raise E('REQUEST_AUTH')
    v={0:1,1:PROFILE,2:cap[3],3:capability_id(capability),4:pub,5:action,6:lease_id,7:operation_id,8:payload_id(action,payload)}
    call_shape(v);return signed(provider,subject_seed,'request-sign',v)

def verify_call(provider,authority,keeper,capability,raw,action,lease_id,payload=None):
    cap=verify_capability(provider,authority,keeper,capability);v,o=split(raw);call_shape(v)
    try:provider.verify(cap[4],domain('keeper-local/request-sign',[o[0]]),o[1])
    except Exception:raise E('REQUEST_AUTH') from None
    if (v[2],v[3],v[4],v[5],v[6],v[8])!=(keeper,capability_id(capability),cap[4],action,lease_id,payload_id(action,payload)):raise E('REQUEST_SCOPE')
    if action not in cap[6]:raise E('METHOD_DENIED')
    return v

def pin_values(pin):
    if type(pin) is not Pin:raise E('CONTRACT_SCHEMA')
    return [pin.app,pin.space,pin.head,pin.sequence,pin.epoch,pin.recipient_id,pin.certificate_id,list(pin.roots),pin.index_id]
def pin_from(v):
    if type(v) is not list or len(v)!=9 or type(v[7]) is not list:raise E('CONTRACT_SCHEMA')
    return Pin(*v[:7],tuple(v[7]),v[8])
def reserve_payload(index,pin,seconds):
    integer(seconds,1,MAX_SECONDS)
    try:inspect_index(index,pin)
    except Exception:raise E('INDEX_INVALID') from None
    return [index_id(index),hashed('keeper-local/pin',[pin_values(pin)]),seconds]
def put_payload(oid,raw):
    from par_recovery.contract import MAX_OBJECT
    fixed(oid)
    if type(raw) is not bytes or not 1<=len(raw)<=MAX_OBJECT:raise E('OBJECT_LIMIT')
    import hashlib
    return [oid,len(raw),hashlib.sha256(raw).digest()]
def inventory(index,pin):
    try:v,_=inspect_index(index,pin)
    except Exception:raise E('INDEX_INVALID') from None
    ds=tuple((d[0],d[1],d[2]) for d in v[15])
    # Recovery inventory may exceed this module's small signed-message limit.
    raw=encode([list(d) for d in ds],max_bytes=524288)
    return ds,hashed('keeper-local/inventory',[raw]),sum(d[2] for d in ds)

def receipt_body(index,pin,keeper,lease_id,authority,capability,call,origin_nonce,generation,tick,seconds):
    ds,iid,total=inventory(index,pin);req,_=split(call)
    return {0:1,1:PROFILE,2:keeper,3:lease_id,4:pin.app,5:pin.space,6:pin.head,7:pin.sequence,8:pin.epoch,
            9:pin.index_id,10:iid,11:len(ds),12:total,13:total+len(index),14:authority_body(authority),
            15:origin_nonce,16:req[7],17:generation,18:tick.boot,19:tick.ns,20:tick.ns+seconds*10**9,
            21:seconds,22:'OPAQUE_BYTES_RETAINED',23:False,24:capability_id(capability)}
def receipt_shape(v):
    keys(v,range(25));integer(v[0],1,1)
    if v[1]!=PROFILE or v[22]!='OPAQUE_BYTES_RETAINED' or v[23] is not False:raise E('CONTRACT_SCHEMA')
    for k in (2,3,5,6,9,10,15,16,18,24):fixed(v[k])
    try:app_id(v[4])
    except Exception:raise E('CONTRACT_SCHEMA') from None
    for k in (7,8,11,12,13,17):integer(v[k],1)
    integer(v[19]);integer(v[20]);integer(v[21],1,MAX_SECONDS)
    if v[20]!=v[19]+v[21]*10**9:raise E('CONTRACT_SCHEMA')
    authority_from(v[14])
def check_receipt(provider,raw,keeper,index,pin,lease_id):
    v,o=split(raw);receipt_shape(v)
    try:provider.verify(keeper,domain('keeper-local/receipt-sign',[o[0]]),o[1])
    except Exception:raise E('RECEIPT_SIGNATURE') from None
    ds,iid,total=inventory(index,pin)
    expect={2:keeper,3:lease_id,4:pin.app,5:pin.space,6:pin.head,7:pin.sequence,8:pin.epoch,9:pin.index_id,10:iid,11:len(ds),12:total,13:total+len(index)}
    if any(v[k]!=value for k,value in expect.items()):raise E('RECEIPT_SCOPE')
    return v

def verify_receipt(provider,raw,keeper,index,pin,lease_id,authority,operation_id,grant_id):
    v=check_receipt(provider,raw,keeper,index,pin,lease_id)
    if (v[14],v[16],v[24])!=(authority_body(authority),operation_id,grant_id):raise E('RECEIPT_SCOPE')
    return v
