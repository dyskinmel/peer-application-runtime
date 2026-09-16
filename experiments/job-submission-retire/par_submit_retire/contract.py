"""Dual-signed, exact-target requests. Operator authority is not job authority."""
from par_job_submit import protocol as s
from par_crypto.primitives import domain
E=s.E
PROFILE='job-submission-retire-local-v1'
MAX_REQUEST=8192
MAX_JOURNAL=65536
MAX_APPROVALS=8
PHASES=('INTENT','PAYLOAD_REMOVED','TOMBSTONED')
fixed=s.fixed
integer=s.integer
keys=s.keys
sha=s.sha

def dump(value,limit=MAX_JOURNAL):
    return s.dump(value,limit)

def target_shape(t):
    keys(t,range(5))
    if type(t[0]) is not bool:raise E('RETIRE_SCHEMA')
    integer(t[1],0,s.MAX_PAYLOAD);fixed(t[2])
    if t[0]:
        integer(t[3],0,2**64-1);integer(t[4],1,2**64-1)
    elif (t[1],t[2],t[3],t[4])!=(0,sha(b''),None,None):
        raise E('RETIRE_SCHEMA')

def request_shape(b):
    keys(b,range(13));integer(b[0],1,1)
    if type(b[1]) is not str or b[1]!=PROFILE:raise E('RETIRE_PROFILE')
    for n in (2,3,4,5,6,8,10,11):fixed(b[n])
    target_shape(b[7]);integer(b[9],1,2**53-1)
    if b[12] is not None:fixed(b[12])

def make_request(p,operator_seed,origin_seed,*,keeper,store,job_id,descriptor_hash,stage_hash,target,revision,nonce,previous=None):
    b={0:1,1:PROFILE,2:keeper,3:store,4:job_id,5:descriptor_hash,6:stage_hash,7:target,
       8:p.sign_public(operator_seed),9:revision,10:p.sign_public(origin_seed),11:nonce,12:previous}
    request_shape(b);raw=dump(b,MAX_REQUEST)
    return dump({0:raw,1:p.sign(operator_seed,domain(PROFILE+'/operator',[raw])),
                 2:p.sign(origin_seed,domain(PROFILE+'/origin',[raw]))},MAX_REQUEST)

def split_request(raw):
    o=s.load(raw,MAX_REQUEST);keys(o,range(3));fixed(o[1],64);fixed(o[2],64)
    if type(o[0]) is not bytes:raise E('RETIRE_SCHEMA')
    b=s.load(o[0],MAX_REQUEST);request_shape(b);return b,o

def check_request(p,raw):
    b,o=split_request(raw)
    try:
        p.verify(b[8],domain(PROFILE+'/operator',[o[0]]),o[1])
        p.verify(b[10],domain(PROFILE+'/origin',[o[0]]),o[2])
    except Exception:raise E('RETIRE_SIGNATURE') from None
    return b

def pack_record(p,seed,b):
    raw=dump(b);return dump({0:raw,1:p.sign(seed,domain(PROFILE+'/record',[raw]))})

def unpack_record(p,public,raw):
    o=s.load(raw,MAX_JOURNAL);keys(o,range(2));fixed(o[1],64)
    if type(o[0]) is not bytes:raise E('RETIRE_SCHEMA')
    try:p.verify(public,domain(PROFILE+'/record',[o[0]]),o[1])
    except Exception:raise E('RETIRE_SIGNATURE') from None
    b=s.load(o[0],MAX_JOURNAL);keys(b,range(10));integer(b[0],1,1)
    if type(b[1]) is not str or b[1]!=PROFILE:raise E('RETIRE_PROFILE')
    for n in (2,3,4):fixed(b[n])
    if type(b[5]) is not bytes or not 1<=len(b[5])<=s.MAX_RECORD:raise E('RETIRE_SCHEMA')
    target_shape(b[6])
    if type(b[7]) is not list or not 1<=len(b[7])<=MAX_APPROVALS:raise E('RETIRE_CAPACITY')
    if type(b[8]) is not str or b[8] not in PHASES:raise E('RETIRE_STATE')
    if b[9] is not None:fixed(b[9])
    return b
