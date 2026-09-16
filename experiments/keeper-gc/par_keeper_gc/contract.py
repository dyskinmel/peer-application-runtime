"""Candidate GC domain. Release proof alone is deliberately NOT a deletion request."""
from par_keeper.contract import (fixed,integer,keys,split,dump,signed,authority_body,
    verify_capability,capability_id,capability_shape,load)
from par_keeper.errors import KeeperError as E
from par_crypto.primitives import hashed,domain
from par_wire.codec import encode,decode

PROFILE='keeper-gc-local-v1'
MAX_INTENT=262144

def request_shape(v):
    keys(v,range(9));integer(v[0],1,1)
    if v[1]!=PROFILE:raise E('CONTRACT_SCHEMA')
    for k in (2,3,4,5,7,8):fixed(v[k])
    integer(v[6])

def make_request(provider,seed,capability,lease,generation,release_id,nonce):
    cap,_=split(capability);capability_shape(cap)
    v={0:1,1:PROFILE,2:cap[3],3:capability_id(capability),4:provider.sign_public(seed),
       5:lease,6:generation,7:release_id,8:nonce}
    request_shape(v)
    if v[4]!=cap[4]:raise E('GC_SIGNATURE')
    return signed(provider,seed,'gc-request-sign',v)

def verify_request(provider,authority,keeper,capability,raw):
    cap=verify_capability(provider,authority,keeper,capability)
    v,o=split(raw);request_shape(v)
    try:provider.verify(cap[4],domain('keeper-local/gc-request-sign',[o[0]]),o[1])
    except Exception:raise E('GC_SIGNATURE') from None
    if (v[2],v[3],v[4])!=(keeper,capability_id(capability),cap[4]):raise E('GC_SCOPE')
    if 'release' not in cap[6]:raise E('METHOD_DENIED')
    return v,cap

def request_id(raw):return hashed('keeper-local/gc-request-id',[raw])
def operation_id(v):return hashed('keeper-local/gc-operation-id',[v[2],v[4],v[8]])

def large_dump(v):
    try:return encode(v,max_bytes=MAX_INTENT)
    except Exception:raise E('CONTRACT_SCHEMA') from None

def large_load(raw):
    try:
        if type(raw) is not bytes or not 0<len(raw)<=MAX_INTENT:raise ValueError()
        v=decode(raw,max_bytes=MAX_INTENT)
        if large_dump(v)!=raw:raise ValueError()
        return v
    except Exception:raise E('CONTRACT_SCHEMA') from None

def sign_intent(provider,seed,body):
    raw=large_dump(body)
    return large_dump({0:raw,1:provider.sign(seed,domain('keeper-local/gc-intent-sign',[raw]))})

def verify_intent(provider,raw,keeper):
    o=large_load(raw);keys(o,(0,1));fixed(o[1],64)
    try:provider.verify(keeper,domain('keeper-local/gc-intent-sign',[o[0]]),o[1])
    except Exception:raise E('GC_SIGNATURE') from None
    body=large_load(o[0]);keys(body,range(14))
    if body[0]!=1 or type(body[0]) is not int or body[1]!=PROFILE or body[2]!=keeper:raise E('CONTRACT_SCHEMA')
    for k in (2,3,4,5,7):fixed(body[k])
    for k in (6,11,12,13):integer(body[k])
    if type(body[9]) is not list or type(body[10]) is not list:raise E('CONTRACT_SCHEMA')
    return body

def result_body(keeper,request,intent):
    return {0:1,1:PROFILE,2:keeper,3:request_id(request),4:intent[3],5:intent[11],6:intent[12],
            7:intent[13],8:'RECLAIMED',9:False,10:False}

def verify_result(provider,raw,keeper,request):
    v,o=split(raw);keys(v,range(11));integer(v[0],1,1)
    req,_=split(request);request_shape(req)
    try:provider.verify(keeper,domain('keeper-local/gc-result-sign',[o[0]]),o[1])
    except Exception:raise E('GC_SIGNATURE') from None
    if (v[1],v[2],v[3],v[4],v[8],v[9],v[10])!=(PROFILE,keeper,request_id(request),req[5],'RECLAIMED',False,False):raise E('GC_SCOPE')
    for k in (5,6,7):integer(v[k])
    return {'state':v[8],'reservation_released_bytes':v[5],'retained_index_charge_bytes':v[6],
            'unlinked_payload_bytes':v[7],'filesystem_free_space_proven':False,'secure_erasure_proven':False}
