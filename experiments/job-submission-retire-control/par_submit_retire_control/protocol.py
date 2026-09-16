"""Domain-separated retirement requests on a legacy-compatible signed hello.

A current controller connection is not origin approval. Both inner signatures
are independently validated for mutations. No profile fallback is allowed.
"""
from __future__ import annotations
import re,json,copy
from par_job_submit import protocol as s
from par_submit_retire import contract as r
from par_crypto.primitives import domain
E=s.E
PROFILE='job-submission-retire-control-local-v1'
MAX_REQUEST=s.MAX_REQUEST
MAX_RESPONSE=s.MAX_RESPONSE
MAX_HELLO=s.MAX_HELLO
METHODS=('proposal','status','reconcile_registration','retire','rebind')
MUTATIONS=('reconcile_registration','retire','rebind')

def signed(p,seed,label,body,limit):
    raw=s.dump(body,limit)
    return s.dump({0:raw,1:p.sign(seed,domain(PROFILE+'/'+label,[raw]))},limit)

def verify(p,public,obj,label):
    s.fixed(public)
    try:p.verify(public,domain(PROFILE+'/'+label,[obj[0]]),obj[1])
    except Exception:raise E('RETIRE_CONTROL_SIGNATURE') from None

def version(b):
    s.integer(b[0],1,1)
    if type(b[1]) is not str or b[1]!=PROFILE:raise E('RETIRE_CONTROL_PROFILE')

def request_shape(p,b):
    s.keys(b,range(6));version(b);s.fixed(b[2])
    if type(b[3]) is not str or b[3] not in METHODS:raise E('RETIRE_CONTROL_METHOD')
    d=s.check_descriptor(p,b[4])
    if b[3] in MUTATIONS:
        a=r.check_request(p,b[5])
        if (a[2],a[3],a[4],a[5],a[10])!=(d[2],d[3],d[5],s.sha(b[4]),d[4]):
            raise E('RETIRE_CONTROL_TARGET')
    elif b[5] is not None:raise E('RETIRE_CONTROL_SCHEMA')
    return d

def make_request(p,seed,hello,action,descriptor,authorization=None):
    h,_=s.split(hello,MAX_HELLO)
    s.check_hello(p,h[2],h[3],p.sign_public(seed),h[5],hello)
    b={0:1,1:PROFILE,2:s.sha(hello),3:action,4:descriptor,5:authorization}
    d=request_shape(p,b)
    if (d[2],d[3])!=(h[2],h[3]):raise E('RETIRE_CONTROL_TARGET')
    if authorization is not None:
        a=r.check_request(p,authorization)
        if (a[8],a[9])!=(h[4],h[5]):raise E('STALE_CONTROLLER')
    return signed(p,seed,'request',b,MAX_REQUEST)

def check_request(p,keeper,store,controller,revision,hello,raw):
    s.check_hello(p,keeper,store,controller,revision,hello)
    b,o=s.split(raw,MAX_REQUEST);d=request_shape(p,b);verify(p,controller,o,'request')
    if b[2]!=s.sha(hello):raise E('RETIRE_CONTROL_CONNECTION')
    if (d[2],d[3])!=(keeper,store):raise E('RETIRE_CONTROL_TARGET')
    if b[5] is not None:
        a=r.check_request(p,b[5])
        if (a[8],a[9])!=(controller,revision):raise E('STALE_CONTROLLER')
    return b

def hex_id(v):
    if type(v) is not str or re.fullmatch('[a-f0-9]{64}',v) is None:raise E('RETIRE_CONTROL_VIEW')

def proposal_shape(v):
    if type(v) is not dict or set(v)!={'keeper','store','job_id','descriptor_hash','stage_hash','target','previous'}:
        raise E('RETIRE_CONTROL_VIEW')
    for k in ('keeper','store','job_id','descriptor_hash','stage_hash'):s.fixed(v[k])
    r.target_shape(v['target'])
    if v['previous'] is not None:s.fixed(v['previous'])

def retirement_shape(v):
    expected={'job_id','state','reservation_released_bytes','removed_payload_bytes','approvals',
              'registered_job_digest','job_cancelled','records_reclaimed','secure_erase','physical_disk_quota','product_qualified'}
    if type(v) is not dict or set(v)!=expected:raise E('RETIRE_CONTROL_VIEW')
    hex_id(v['job_id'])
    if type(v['state']) is not str or v['state'] not in r.PHASES:raise E('RETIRE_CONTROL_VIEW')
    for k in ('reservation_released_bytes','removed_payload_bytes'):s.integer(v[k],0,s.MAX_PAYLOAD)
    s.integer(v['approvals'],1,r.MAX_APPROVALS)
    if v['registered_job_digest'] is not None:hex_id(v['registered_job_digest'])
    for k in ('job_cancelled','records_reclaimed','secure_erase','physical_disk_quota','product_qualified'):
        if v[k] is not False:raise E('RETIRE_CONTROL_VIEW')
    if v['state']!='TOMBSTONED' and (v['reservation_released_bytes'] or v['removed_payload_bytes']):
        raise E('RETIRE_CONTROL_VIEW')
    if v['state']=='TOMBSTONED' and not 13<=v['reservation_released_bytes']<=s.MAX_PAYLOAD:
        raise E('RETIRE_CONTROL_VIEW')

def view_shape(v):
    common={'kind','job_id','descriptor_hash','stage_state','controller_revision','product_qualified'}
    if type(v) is not dict or v.get('kind') not in ('proposal','status'):raise E('RETIRE_CONTROL_VIEW')
    extra='proposal' if v['kind']=='proposal' else 'retirement'
    if set(v)!=common|{extra}:raise E('RETIRE_CONTROL_VIEW')
    hex_id(v['job_id']);hex_id(v['descriptor_hash']);s.integer(v['controller_revision'],1,2**53-1)
    if type(v['stage_state']) is not str or v['stage_state'] not in s.STATES or v['product_qualified'] is not False:
        raise E('RETIRE_CONTROL_VIEW')
    if extra=='proposal':
        proposal_shape(v[extra])
        if (v[extra]['job_id'].hex(),v[extra]['descriptor_hash'].hex())!=(v['job_id'],v['descriptor_hash']):raise E('RETIRE_CONTROL_VIEW')
    elif v[extra] is not None:
        retirement_shape(v[extra])
        if v[extra]['job_id']!=v['job_id'] or v['stage_state']=='INFLIGHT':raise E('RETIRE_CONTROL_VIEW')
        if (v[extra]['registered_job_digest'] is not None)!=(v['stage_state']=='REGISTERED'):raise E('RETIRE_CONTROL_VIEW')

def make_response(p,seed,hello,request,ok,value):
    if type(ok) is not bool:raise E('RETIRE_CONTROL_VIEW')
    if ok:
        view_shape(value);value=encode_view(value)
    elif type(value) is not str or re.fullmatch('[A-Z_]{1,64}',value) is None:raise E('RETIRE_CONTROL_VIEW')
    return signed(p,seed,'response',{0:1,1:PROFILE,2:s.sha(hello),3:s.sha(request),4:ok,5:value,6:False},MAX_RESPONSE)

def check_response(p,keeper,hello,request,raw):
    b,o=s.split(raw,MAX_RESPONSE);s.keys(b,range(7));version(b);verify(p,keeper,o,'response')
    if type(b[4]) is not bool or b[6] is not False or (b[2],b[3])!=(s.sha(hello),s.sha(request)):
        raise E('RETIRE_CONTROL_RESPONSE')
    if not b[4]:
        if type(b[5]) is not str or re.fullmatch('[A-Z_]{1,64}',b[5]) is None:raise E('RETIRE_CONTROL_VIEW')
        raise E('REMOTE_'+b[5])
    v=decode_view(b[5]);view_shape(v);q,_=s.split(request,MAX_REQUEST);d=request_shape(p,q);h,_=s.split(hello,MAX_HELLO)
    expected='proposal' if q[3]=='proposal' else 'status'
    if (v['kind'],v['job_id'],v['descriptor_hash'],v['controller_revision'])!=(expected,d[5].hex(),s.sha(q[4]).hex(),h[5]):
        raise E('RETIRE_CONTROL_RESPONSE')
    if expected=='proposal' and (v['proposal']['keeper'],v['proposal']['store'])!=(keeper,h[3]):raise E('RETIRE_CONTROL_RESPONSE')
    if expected=='status' and v['retirement'] is not None:
        t=v['retirement']
        if t['state']=='TOMBSTONED' and (t['reservation_released_bytes']!=d[7] or t['removed_payload_bytes']>d[7]):raise E('RETIRE_CONTROL_RESPONSE')
    # Detached, validated value; no cached/mutable authority is returned.
    return copy.deepcopy(v)


def encode_view(v):
    """Canonical JSON nested as bytes in CBOR; no relaxation of PAR map keys."""
    w=copy.deepcopy(v)
    if w['kind']=='proposal':
        p=w['proposal']
        for k in ('keeper','store','job_id','descriptor_hash','stage_hash'):p[k]=p[k].hex()
        if p['previous'] is not None:p['previous']=p['previous'].hex()
        t=p['target'];p['target']=[t[0],t[1],t[2].hex(),t[3],t[4]]
    return s.json_bytes(w)

def decode_view(raw):
    if type(raw) is not bytes:raise E('RETIRE_CONTROL_VIEW')
    try:
        w=json.loads(raw,object_pairs_hook=s._pairs)
        if s.json_bytes(w)!=raw or type(w) is not dict:raise ValueError()
        if w.get('kind')=='proposal':
            p=w['proposal']
            for k in ('keeper','store','job_id','descriptor_hash','stage_hash'):
                hex_id(p[k]);p[k]=bytes.fromhex(p[k])
            if p['previous'] is not None:hex_id(p['previous']);p['previous']=bytes.fromhex(p['previous'])
            t=p['target']
            if type(t) is not list or len(t)!=5:raise ValueError()
            hex_id(t[2]);p['target']={0:t[0],1:t[1],2:bytes.fromhex(t[2]),3:t[3],4:t[4]}
        return w
    except Exception:raise E('RETIRE_CONTROL_VIEW') from None
