"""Explicit controller identity; connection proof is NOT a management grant.

Only pre-registered job IDs can be controlled. Stable intents survive reconnects;
connection envelopes cannot. All keys/fields/types are exact; no dynamic dispatch.
"""
from dataclasses import dataclass, field
import json, re
from par_keeper_service.protocol import fixed, integer, keys, dump, load
from par_keeper_service.errors import ServiceError as E
from par_crypto.primitives import domain, hashed

PROFILE='host-job-control-local-v1'
MAX_HELLO=4096
MAX_REQUEST=16384
MAX_RESPONSE=65536
MAX_INTENT=2048
ACTIONS=('status','select','cancel','reconcile','retry')
MUTATIONS=frozenset(ACTIONS)-{'status'}
ERRORS=frozenset(('REJECTED','INTERNAL','CONTROL_UNCERTAIN','STALE_CONTROLLER','CAPACITY'))

def digest(raw):return hashed('host-job-control/bytes',[raw])
def _sign(p,seed,label,body,limit):
    raw=dump(body,limit)
    return dump({0:raw,1:p.sign(seed,domain('host-job-control/'+label,[raw]))},limit)
def _split(raw,limit):
    o=load(raw,limit);keys(o,(0,1));fixed(o[1],64)
    b=load(o[0],limit);return b,o

def _verify(p,public,o,label):
    fixed(public)
    try:p.verify(public,domain('host-job-control/'+label,[o[0]]),o[1])
    except Exception:raise E('CONTROL_SIGNATURE') from None

def _version(b):
    integer(b[0],1,1)
    if type(b[1]) is not str or b[1]!=PROFILE:raise E('CONTROL_PROFILE')

def hello_shape(b):
    keys(b,range(11));_version(b)
    for k in (2,3,4,5):fixed(b[k])
    if b[6] is not None:fixed(b[6])
    integer(b[7],1,2**53-1);integer(b[8],50,30000)
    integer(b[9],MAX_REQUEST,MAX_REQUEST);integer(b[10],MAX_RESPONSE,MAX_RESPONSE)

def make_hello(p,seed,*,store,controller,revision,boot,challenge,deadline_ms):
    b={0:1,1:PROFILE,2:p.sign_public(seed),3:store,4:boot,5:challenge,6:controller,7:revision,8:deadline_ms,9:MAX_REQUEST,10:MAX_RESPONSE}
    hello_shape(b);return _sign(p,seed,'hello',b,MAX_HELLO)

def check_hello(p,keeper,store,controller,revision,raw):
    fixed(keeper);fixed(store);fixed(controller);integer(revision,1,2**53-1)
    b,o=_split(raw,MAX_HELLO);hello_shape(b);_verify(p,keeper,o,'hello')
    if (b[2],b[3],b[6],b[7])!=(keeper,store,controller,revision):raise E('CONTROL_PEER')
    return b

@dataclass(frozen=True)
class Intent:
    action:str
    job_id:bytes|None
    operation_id:bytes
    controller:bytes
    revision:int
    raw:bytes=field(repr=False)

def intent_shape(b):
    keys(b,range(9));_version(b)
    for k in (2,3,4,6):fixed(b[k])
    integer(b[5],1,2**53-1)
    if type(b[7]) is not str or b[7] not in ACTIONS:raise E('CONTROL_METHOD')
    if b[8] is None:
        if b[7]!='status':raise E('CONTROL_JOB')
    else:fixed(b[8])

def make_intent(p,seed,*,keeper,store,revision,operation_id,action,job_id):
    b={0:1,1:PROFILE,2:keeper,3:store,4:p.sign_public(seed),5:revision,6:operation_id,7:action,8:job_id}
    intent_shape(b);return _sign(p,seed,'intent',b,MAX_INTENT)

def inspect_intent(p,raw):
    b,o=_split(raw,MAX_INTENT);intent_shape(b);_verify(p,b[4],o,'intent')
    return b,Intent(b[7],b[8],b[6],b[4],b[5],raw)

def check_intent(p,keeper,store,controller,revision,raw):
    fixed(keeper);fixed(store);fixed(controller);integer(revision,1,2**53-1)
    b,i=inspect_intent(p,raw)
    if (b[2],b[3],b[4],b[5])!=(keeper,store,controller,revision):raise E('STALE_CONTROLLER')
    return i

def make_request(p,seed,hello,intent):
    b,i=inspect_intent(p,intent)
    if p.sign_public(seed)!=i.controller:raise E('CONTROL_SIGNATURE')
    check_hello(p,b[2],b[3],i.controller,i.revision,hello)
    return _sign(p,seed,'request',{0:1,1:PROFILE,2:digest(hello),3:intent},MAX_REQUEST)

def check_request(p,keeper,store,controller,revision,hello,raw):
    check_hello(p,keeper,store,controller,revision,hello)
    b,o=_split(raw,MAX_REQUEST);keys(b,range(4));_version(b);fixed(b[2])
    if b[2]!=digest(hello):raise E('CONTROL_CONNECTION')
    i=check_intent(p,keeper,store,controller,revision,b[3]);_verify(p,controller,o,'request')
    return i

def json_bytes(value):
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    except (ValueError,TypeError):raise E('CONTROL_VIEW') from None

def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate')
        d[k]=v
    return d

def view_shape(v):
    expected={'operation_id','action','job_id','outcome','error','duplicate','job','host','jobs_pin','control_pin','policy_revision','product_qualified'}
    if type(v) is not dict or set(v)!=expected:raise E('CONTROL_VIEW')
    def hx(x):
        if type(x) is not str or re.fullmatch('[a-f0-9]{64}',x) is None:raise E('CONTROL_VIEW')
    hx(v['operation_id'])
    if v['job_id'] is not None:hx(v['job_id'])
    if type(v['action']) is not str or v['action'] not in ACTIONS:raise E('CONTROL_VIEW')
    if type(v['outcome']) is not str or v['outcome'] not in ('STATUS','ACCEPTED','REJECTED','OUTCOME_UNKNOWN'):raise E('CONTROL_VIEW')
    if type(v['duplicate']) is not bool or v['product_qualified'] is not False:raise E('CONTROL_VIEW')
    if v['error'] is not None and (type(v['error']) is not str or re.fullmatch('[A-Z_]{1,64}',v['error']) is None):raise E('CONTROL_VIEW')
    if (v['outcome']=='REJECTED')!=(v['error'] is not None):raise E('CONTROL_VIEW')
    integer(v['policy_revision'],1,2**53-1)
    for k in ('jobs_pin','control_pin'):
        if type(v[k]) is not str or len(v[k])>40000 or len(v[k])%2 or re.fullmatch('[a-f0-9]+',v[k]) is None:raise E('CONTROL_VIEW')
    host=v['host'];hk={'mode','selected_job','connections','reader_pins','read_accepting','upload_accepting','fault','effect_steps','native_storage_preemption'}
    if type(host) is not dict or set(host)!=hk:raise E('CONTROL_VIEW')
    if type(host['mode']) is not str or host['mode'] not in ('SERVING','DRAINING','REVIEW_REQUIRED'):raise E('CONTROL_VIEW')
    if host['selected_job'] is not None:hx(host['selected_job'])
    for k in ('connections','reader_pins','effect_steps'):integer(host[k],0,2**53-1)
    for k in ('read_accepting','upload_accepting'):
        if type(host[k]) is not bool:raise E('CONTROL_VIEW')
    if host['native_storage_preemption'] is not False:raise E('CONTROL_VIEW')
    if host['fault'] is not None and (type(host['fault']) is not str or re.fullmatch('[A-Z_]{1,64}',host['fault']) is None):raise E('CONTROL_VIEW')
    j=v['job']
    if v['job_id'] is None:
        if j is not None or v['action']!='status':raise E('CONTROL_VIEW')
    else:
        fields={'job_id','action','state','journal_state','revision','input_digest','target_sequence','cancellable','may_have_effect','requires_reconciliation','explicit_retry_required','result_verified','result_digest','waiting_reason','progress_total','product_qualified'}
        if type(j) is not dict or set(j)!=fields or j['job_id']!=v['job_id']:raise E('CONTROL_VIEW')
        states=('QUEUED','VALIDATED','PREPARED','OUTCOME_UNKNOWN','RETRY_READY','SUCCEEDED','CANCELLED')
        if type(j['state']) is not str or j['state'] not in states or j['journal_state'] not in states+('EXECUTING',):raise E('CONTROL_VIEW')
        if type(j['action']) is not str or j['action'] not in ('retire','close','compact','open'):raise E('CONTROL_VIEW')
        for k in ('revision','target_sequence'):integer(j[k],0,2**53-1)
        hx(j['input_digest'])
        if j['result_digest'] is not None:hx(j['result_digest'])
        for k in ('cancellable','may_have_effect','requires_reconciliation','explicit_retry_required','result_verified'):
            if type(j[k]) is not bool:raise E('CONTROL_VIEW')
        if j['product_qualified'] is not False or j['progress_total'] is not None:raise E('CONTROL_VIEW')
        if j['waiting_reason'] not in (None,'ACTIVE_TRANSFERS'):raise E('CONTROL_VIEW')
        if j['result_verified']!=(j['state']=='SUCCEEDED') or (j['result_digest'] is not None)!=j['result_verified']:raise E('CONTROL_VIEW')
        if j['cancellable']!=(j['state'] in ('QUEUED','VALIDATED','PREPARED')):raise E('CONTROL_VIEW')
        if j['state']!=('OUTCOME_UNKNOWN' if j['journal_state']=='EXECUTING' else j['journal_state']):raise E('CONTROL_VIEW')
        if j['requires_reconciliation']!=(j['journal_state'] in ('EXECUTING','OUTCOME_UNKNOWN')):raise E('CONTROL_VIEW')
        if j['explicit_retry_required']!=(j['state']=='RETRY_READY'):raise E('CONTROL_VIEW')

def make_response(p,seed,hello,request,ok,value):
    if type(ok) is not bool:raise E('CONTROL_VIEW')
    if ok:view_shape(value);value=json_bytes(value)
    elif type(value) is not str or value not in ERRORS:raise E('CONTROL_VIEW')
    return _sign(p,seed,'response',{0:1,1:PROFILE,2:digest(hello),3:digest(request),4:ok,5:value,6:False},MAX_RESPONSE)

def check_response(p,keeper,hello,request,raw):
    b,o=_split(raw,MAX_RESPONSE);keys(b,range(7));_version(b);_verify(p,keeper,o,'response')
    if type(b[4]) is not bool or b[6] is not False or (b[2],b[3])!=(digest(hello),digest(request)):raise E('CONTROL_RESPONSE')
    if not b[4]:
        if type(b[5]) is not str or b[5] not in ERRORS:raise E('CONTROL_VIEW')
        raise E('REMOTE_'+b[5])
    try:v=json.loads(b[5],object_pairs_hook=_pairs)
    except Exception:raise E('CONTROL_VIEW') from None
    view_shape(v)
    if json_bytes(v)!=b[5]:raise E('CONTROL_VIEW')
    r,_=_split(request,MAX_REQUEST);_,i=inspect_intent(p,r[3])
    if (v['operation_id'],v['action'],v['job_id'],v['policy_revision'])!=(i.operation_id.hex(),i.action,i.job_id.hex() if i.job_id else None,i.revision):raise E('CONTROL_RESPONSE')
    return v
