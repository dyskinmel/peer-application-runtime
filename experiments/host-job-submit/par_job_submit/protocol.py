"""Private signed job-submission candidate. Controller proof is not job authority."""
from __future__ import annotations
import hashlib,json,re
from par_keeper_service.protocol import fixed,integer,keys,dump,load
from par_keeper_service.errors import ServiceError as E
from par_crypto.primitives import domain
from par_management_jobs import contract as j
PROFILE='host-job-submit-local-v1'
MAGIC=b'PARJSUB1'
MAX_HEADER=524288
MAX_PAYLOAD=MAX_HEADER+16*1024*1024+12
MAX_DESCRIPTOR=4096
MAX_RECORD=16384
MAX_HELLO=4096
MAX_REQUEST=65536
MAX_RESPONSE=16384
MAX_RECORDS=32
MAX_TOTAL=64*1024*1024
CHUNK=32768
METHODS=('context','begin','chunk','progress','submit','reconcile','retry')
STATES=('RECEIVING','READY','INFLIGHT','RETRY_READY','REGISTERED')

def sha(raw):
    if type(raw) is not bytes:raise E('SUBMIT_INPUT')
    return hashlib.sha256(raw).digest()

def signed(p,seed,label,body,limit):
    raw=dump(body,limit)
    return dump({0:raw,1:p.sign(seed,domain('host-job-submit/'+label,[raw]))},limit)

def split(raw,limit):
    o=load(raw,limit);keys(o,(0,1));fixed(o[1],64)
    if type(o[0]) is not bytes:raise E('SUBMIT_SCHEMA')
    return load(o[0],limit),o

def verify(p,public,o,label):
    fixed(public)
    try:p.verify(public,domain('host-job-submit/'+label,[o[0]]),o[1])
    except Exception:raise E('SUBMIT_SIGNATURE') from None

def version(b):
    integer(b[0],1,1)
    if type(b[1]) is not str or b[1]!=PROFILE:raise E('SUBMIT_PROFILE')

def pack_job(action,command=None,archive=None):
    j.arguments(bytes(32),action,command,archive)
    data=archive or b''
    h=dump({0:1,1:action,2:command,3:len(data),4:sha(data) if data else None},MAX_HEADER)
    return MAGIC+len(h).to_bytes(4,'big')+h+data

def unpack_job(raw):
    if type(raw) is not bytes or not 13<=len(raw)<=MAX_PAYLOAD or raw[:8]!=MAGIC:raise E('SUBMIT_PAYLOAD')
    n=int.from_bytes(raw[8:12],'big');integer(n,1,MAX_HEADER)
    if 12+n>len(raw):raise E('SUBMIT_PAYLOAD')
    b=load(raw[12:12+n],MAX_HEADER);keys(b,range(5));integer(b[0],1,1);integer(b[3],0,j.MAX_ARCHIVE)
    data=raw[12+n:]
    if len(data)!=b[3] or b[4]!=(sha(data) if data else None):raise E('SUBMIT_PAYLOAD')
    j.arguments(bytes(32),b[1],b[2],data or None)
    return b[1],b[2],data or None

def descriptor_shape(b):
    keys(b,range(10));version(b)
    for k in (2,3,4,5,6,8):fixed(b[k])
    integer(b[7],13,MAX_PAYLOAD);integer(b[9],1,2**53-1)

def make_descriptor(p,seed,*,keeper,store,revision,job_id,target,size,payload_hash):
    b={0:1,1:PROFILE,2:keeper,3:store,4:p.sign_public(seed),5:job_id,6:target,7:size,8:payload_hash,9:revision}
    descriptor_shape(b);return signed(p,seed,'descriptor',b,MAX_DESCRIPTOR)

def check_descriptor(p,raw):
    b,o=split(raw,MAX_DESCRIPTOR);descriptor_shape(b);verify(p,b[4],o,'descriptor');return b

def hello_shape(b):
    keys(b,range(12));version(b)
    for k in (2,3,6,7):fixed(b[k])
    if b[4] is not None:fixed(b[4])
    integer(b[5],1,2**53-1);integer(b[8],50,30000)
    integer(b[9],MAX_REQUEST,MAX_REQUEST);integer(b[10],MAX_PAYLOAD,MAX_PAYLOAD);integer(b[11],CHUNK,CHUNK)

def make_hello(p,seed,*,store,controller,revision,boot,challenge,deadline_ms):
    b={0:1,1:PROFILE,2:p.sign_public(seed),3:store,4:controller,5:revision,6:boot,7:challenge,8:deadline_ms,9:MAX_REQUEST,10:MAX_PAYLOAD,11:CHUNK}
    hello_shape(b);return signed(p,seed,'hello',b,MAX_HELLO)

def check_hello(p,keeper,store,controller,revision,raw):
    fixed(controller);integer(revision,1,2**53-1)
    b,o=split(raw,MAX_HELLO);hello_shape(b);verify(p,keeper,o,'hello')
    if (b[2],b[3],b[4],b[5])!=(keeper,store,controller,revision):raise E('SUBMIT_PEER')
    return b

def request_shape(p,b):
    keys(b,range(7));version(b);fixed(b[2])
    if type(b[3]) is not str or b[3] not in METHODS:raise E('SUBMIT_METHOD')
    if b[3]=='context':
        if any(b[k] is not None for k in (4,5,6)):raise E('SUBMIT_SCHEMA')
    else:
        check_descriptor(p,b[4])
        if b[3]=='chunk':
            integer(b[5],0,MAX_PAYLOAD)
            if type(b[6]) is not bytes or not 1<=len(b[6])<=CHUNK:raise E('SUBMIT_CHUNK')
        elif b[5] is not None or b[6] is not None:raise E('SUBMIT_SCHEMA')

def make_request(p,seed,hello,action,descriptor=None,offset=None,data=None):
    h,_=split(hello,MAX_HELLO);check_hello(p,h[2],h[3],p.sign_public(seed),h[5],hello)
    b={0:1,1:PROFILE,2:sha(hello),3:action,4:descriptor,5:offset,6:data};request_shape(p,b)
    if descriptor is not None:
        d=check_descriptor(p,descriptor)
        if (d[2],d[3],d[4],d[9])!=(h[2],h[3],h[4],h[5]):raise E('STALE_CONTROLLER')
    return signed(p,seed,'request',b,MAX_REQUEST)

def check_request(p,keeper,store,controller,revision,hello,raw):
    check_hello(p,keeper,store,controller,revision,hello)
    b,o=split(raw,MAX_REQUEST);request_shape(p,b);verify(p,controller,o,'request')
    if b[2]!=sha(hello):raise E('SUBMIT_CONNECTION')
    if b[4] is not None:
        d=check_descriptor(p,b[4])
        if (d[2],d[3],d[4],d[9])!=(keeper,store,controller,revision):raise E('STALE_CONTROLLER')
    return b

def json_bytes(v):
    try:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    except Exception:raise E('SUBMIT_VIEW') from None

def view_shape(v):
    def hx(x):
        if type(x) is not str or re.fullmatch('[0-9a-f]{64}',x) is None:raise E('SUBMIT_VIEW')
    if type(v) is not dict:raise E('SUBMIT_VIEW')
    if 'target_digest' in v and 'job_id' not in v:
        if set(v)!={'target_digest','controller_revision','max_payload','max_records','product_qualified'}:raise E('SUBMIT_VIEW')
        hx(v['target_digest']);integer(v['controller_revision'],1,2**53-1);integer(v['max_payload'],MAX_PAYLOAD,MAX_PAYLOAD);integer(v['max_records'],1,MAX_RECORDS)
    else:
        if set(v)!={'job_id','state','received','total','prefix_hash','payload_hash','target_digest','registered_job_digest','product_qualified','automatically_selected'}:raise E('SUBMIT_VIEW')
        for k in ('job_id','prefix_hash','payload_hash','target_digest'):hx(v[k])
        if type(v['state']) is not str or v['state'] not in STATES:raise E('SUBMIT_VIEW')
        integer(v['total'],13,MAX_PAYLOAD);integer(v['received'],0,v['total'])
        if v['state']!='RECEIVING' and (v['received']!=v['total'] or v['prefix_hash']!=v['payload_hash']):raise E('SUBMIT_VIEW')
        if v['received']==0 and v['prefix_hash']!=sha(b'').hex():raise E('SUBMIT_VIEW')
        if (v['registered_job_digest'] is not None)!=(v['state']=='REGISTERED'):raise E('SUBMIT_VIEW')
        if v['registered_job_digest'] is not None:hx(v['registered_job_digest'])
        if v['automatically_selected'] is not False:raise E('SUBMIT_VIEW')
    if v['product_qualified'] is not False:raise E('SUBMIT_VIEW')

def make_response(p,seed,hello,request,ok,value):
    if type(ok) is not bool:raise E('SUBMIT_VIEW')
    if ok:view_shape(value);value=json_bytes(value)
    elif type(value) is not str or re.fullmatch('[A-Z_]{1,64}',value) is None:raise E('SUBMIT_VIEW')
    return signed(p,seed,'response',{0:1,1:PROFILE,2:sha(hello),3:sha(request),4:ok,5:value,6:False},MAX_RESPONSE)

def _pairs(items):
    out={}
    for k,v in items:
        if k in out:raise ValueError('duplicate key')
        out[k]=v
    return out

def check_response(p,keeper,hello,request,raw):
    b,o=split(raw,MAX_RESPONSE);keys(b,range(7));version(b);verify(p,keeper,o,'response')
    if type(b[4]) is not bool or b[6] is not False or (b[2],b[3])!=(sha(hello),sha(request)):raise E('SUBMIT_RESPONSE')
    if not b[4]:
        if type(b[5]) is not str or re.fullmatch('[A-Z_]{1,64}',b[5]) is None:raise E('SUBMIT_VIEW')
        raise E('REMOTE_'+b[5])
    try:v=json.loads(b[5],object_pairs_hook=_pairs)
    except Exception:raise E('SUBMIT_VIEW') from None
    view_shape(v)
    if json_bytes(v)!=b[5]:raise E('SUBMIT_VIEW')
    r,_=split(request,MAX_REQUEST)
    if r[3]=='context':
        if 'job_id' in v:raise E('SUBMIT_RESPONSE')
        h,_=split(hello,MAX_HELLO)
        if v['controller_revision']!=h[5]:raise E('SUBMIT_RESPONSE')
    else:
        if 'job_id' not in v:raise E('SUBMIT_RESPONSE')
        d=check_descriptor(p,r[4])
        if (v['job_id'],v['total'],v['payload_hash'],v['target_digest'])!=(d[5].hex(),d[7],d[8].hex(),d[6].hex()):raise E('SUBMIT_RESPONSE')
    return v
