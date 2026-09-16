"""Candidate repair messages. Repair observations never extend retention receipts."""
from par_keeper.contract import (fixed,integer,keys,split,signed,authority_body,
    verify_capability,capability_id,capability_shape)
from par_keeper.errors import KeeperError as E
from par_crypto.primitives import hashed,domain

PROFILE='keeper-repair-local-v1'
MAX_TARGETS=128
MAX_STAGING=32*1024*1024
MAX_JOBS=256

def targets(v):
    if type(v) is not list or not 1<=len(v)<=MAX_TARGETS:raise E('REPAIR_TARGETS')
    for oid in v:fixed(oid)
    if v!=sorted(set(v)):raise E('REPAIR_TARGETS')

def request_shape(v):
    keys(v,range(10));integer(v[0],1,1)
    if v[1]!=PROFILE:raise E('CONTRACT_SCHEMA')
    for k in (2,3,4,5,7,9):fixed(v[k])
    integer(v[6],1);targets(v[8])

def make_request(provider,seed,capability,lease,generation,index,object_ids,nonce):
    cap,_=split(capability);capability_shape(cap)
    v={0:1,1:PROFILE,2:cap[3],3:capability_id(capability),4:provider.sign_public(seed),5:lease,6:generation,7:index,8:object_ids,9:nonce}
    request_shape(v)
    if v[4]!=cap[4]:raise E('REPAIR_SIGNATURE')
    return signed(provider,seed,'repair-request-sign',v)

def verify_request(provider,authority,keeper,capability,raw):
    cap=verify_capability(provider,authority,keeper,capability);v,o=split(raw);request_shape(v)
    try:provider.verify(cap[4],domain('keeper-local/repair-request-sign',[o[0]]),o[1])
    except Exception:raise E('REPAIR_SIGNATURE') from None
    if (v[2],v[3],v[4],v[7])!=(keeper,capability_id(capability),cap[4],cap[5]):raise E('REPAIR_SCOPE')
    if 'put' not in cap[6]:raise E('METHOD_DENIED')
    return v,cap

def request_id(raw):return hashed('keeper-local/repair-request-id',[raw])
def job_id(v):return hashed('keeper-local/repair-job-id',[v[2],v[4],v[9]])

def cancel_shape(v):
    keys(v,range(8));integer(v[0],1,1)
    if v[1]!=PROFILE:raise E('CONTRACT_SCHEMA')
    for k in range(2,8):fixed(v[k])

def make_cancel(provider,seed,capability,lease,job,nonce):
    cap,_=split(capability);capability_shape(cap)
    v={0:1,1:PROFILE,2:cap[3],3:capability_id(capability),4:provider.sign_public(seed),5:lease,6:job,7:nonce}
    cancel_shape(v)
    if v[4]!=cap[4]:raise E('REPAIR_SIGNATURE')
    return signed(provider,seed,'repair-cancel-sign',v)

def verify_cancel(provider,authority,keeper,capability,raw):
    cap=verify_capability(provider,authority,keeper,capability);v,o=split(raw);cancel_shape(v)
    try:provider.verify(cap[4],domain('keeper-local/repair-cancel-sign',[o[0]]),o[1])
    except Exception:raise E('REPAIR_SIGNATURE') from None
    if (v[2],v[3],v[4])!=(keeper,capability_id(capability),cap[4]):raise E('REPAIR_SCOPE')
    if 'release' not in cap[6]:raise E('METHOD_DENIED')
    return v,cap

def signed_body(provider,raw,keeper,label,expected_keys):
    v,o=split(raw);keys(v,expected_keys);integer(v[0],1,1)
    if v[1]!=PROFILE or v[2]!=keeper:raise E('REPAIR_SCOPE')
    try:provider.verify(keeper,domain('keeper-local/'+label,[o[0]]),o[1])
    except Exception:raise E('REPAIR_SIGNATURE') from None
    return v

def verify_result(provider,raw,keeper,*,expected_request=None):
    fixed(keeper)
    v=signed_body(provider,raw,keeper,'repair-observation-sign',range(16))
    for k in (3,4,5,7,9,10):fixed(v[k])
    integer(v[6],1);integer(v[11]);targets(v[8])
    if type(v[12]) is not bool or v[13]!='TARGET_BYTES_VERIFIED' or v[14] is not False or v[15] is not False:raise E('CONTRACT_SCHEMA')
    if expected_request is not None:
        req,_=split(expected_request);request_shape(req)
        if (v[3],v[4],v[5],v[6],v[7],v[8])!=(job_id(req),request_id(expected_request),req[5],req[6],req[7],req[8]):raise E('REPAIR_SCOPE')
    return {'state':v[13],'job_id':v[3],'lease_id':v[5],'generation':v[6],
        'targets':tuple(v[8]),'all_bytes_observed':v[12],'observed_boot':v[10],'observed_ns':v[11],
        'original_receipt_digest':v[9],'recipient_validated':False,'retention_extended':False,
        'current_health_proven':False,'product_qualified':False}
