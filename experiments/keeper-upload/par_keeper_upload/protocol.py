"""Versioned private upload contract. No change to the read service allowlist.

A stable subject-signed command survives reconnection. An additional signature
binds it to exactly one server challenge. Capability authorization is performed
against the Keeper's known Authority by Spool, never inferred from this parser.
"""
from par_wire.codec import encode,decode
from par_crypto.primitives import domain,hashed
from par_keeper.contract import split,capability_shape,call_shape,pin_from
from par_recovery.contract import MAX_INDEX,MAX_OBJECT
from par_keeper_service.errors import ServiceError as E
from par_keeper_service.protocol import fixed,integer,keys,dump,load

PROFILE='keeper-upload-local-v1'
METHODS=frozenset(('begin','chunk','progress','reserve','put','seal'))
MAX_HELLO=4096;MAX_REQUEST=65536;MAX_RESPONSE=1048576;CHUNK=32768
ERRORS=frozenset(('REJECTED','UNAVAILABLE','DATA_INVALID','STALE_AUTHORITY','BUSY','CAPACITY','OUTCOME_UNKNOWN','INTERNAL'))

def digest(raw):
    if type(raw) is not bytes:raise E('PROTOCOL_SCHEMA')
    return hashed('keeper-upload-local/bytes',[raw])
def _signed(p,seed,label,body,maximum):
    b=dump(body,maximum)
    return dump({0:b,1:p.sign(seed,domain('keeper-upload-local/'+label,[b]))},maximum)
def _split(raw,maximum):
    o=load(raw,maximum);keys(o,(0,1));fixed(o[1],64)
    return load(o[0],maximum),o
def _verify(p,public,o,label):
    fixed(public)
    try:p.verify(public,domain('keeper-upload-local/'+label,[o[0]]),o[1])
    except Exception:raise E('SIGNATURE') from None
def _version(b):
    integer(b[0],1,1)
    if b[1]!=PROFILE:raise E('PROTOCOL_SCHEMA')

def make_hello(p,seed,boot,challenge,deadline_ms):
    fixed(seed);fixed(boot);fixed(challenge);integer(deadline_ms,50,30000)
    return _signed(p,seed,'hello',{0:1,1:PROFILE,2:p.sign_public(seed),3:boot,4:challenge,5:deadline_ms,6:MAX_REQUEST,7:MAX_RESPONSE},MAX_HELLO)
def check_hello(p,public,raw):
    b,o=_split(raw,MAX_HELLO);keys(b,range(8));_version(b)
    for k in (2,3,4):fixed(b[k])
    integer(b[5],50,30000);integer(b[6],MAX_REQUEST,MAX_REQUEST);integer(b[7],MAX_RESPONSE,MAX_RESPONSE)
    _verify(p,public,o,'hello')
    if b[2]!=public:raise E('REQUEST_SCOPE')
    return b

def _shape(b):
    keys(b,range(8));_version(b);fixed(b[3])
    if type(b[2]) is not str or b[2] not in METHODS:raise E('METHOD_DENIED')
    try:cap,_=split(b[4]);capability_shape(cap)
    except Exception:raise E('PROTOCOL_SCHEMA') from None
    action=b[2];payload=b[7]
    if b[6] is not None:fixed(b[6])
    if b[5] is not None:
        try:c,_=split(b[5]);call_shape(c)
        except Exception:raise E('PROTOCOL_SCHEMA') from None
        if (c[2],c[4],c[6])!=(cap[3],cap[4],b[6]):raise E('REQUEST_SCOPE')
    if action=='begin':
        if type(payload) is not list or len(payload)!=4:raise E('PROTOCOL_SCHEMA')
        kind,oid,size,sha=payload
        if type(kind) is not str or kind not in ('index','object'):raise E('PROTOCOL_SCHEMA')
        fixed(oid);fixed(sha);integer(size,1,MAX_INDEX if kind=='index' else MAX_OBJECT)
        if kind=='index':
            if b[6] is not None or b[5] is not None or oid!=cap[5]:raise E('REQUEST_SCOPE')
        elif b[6] is None or b[5] is None:raise E('REQUEST_SCOPE')
    elif action=='chunk':
        if b[5] is not None or type(payload) is not list or len(payload)!=3:raise E('PROTOCOL_SCHEMA')
        fixed(payload[0]);integer(payload[1],0,max(MAX_INDEX,MAX_OBJECT))
        if type(payload[2]) is not bytes or not 1<=len(payload[2])<=CHUNK:raise E('FRAME_LIMIT')
    elif action=='progress':
        if b[5] is not None:raise E('PROTOCOL_SCHEMA')
        fixed(payload)
    elif action=='reserve':
        if b[6] is not None or b[5] is None or type(payload) is not list or len(payload)!=3:raise E('PROTOCOL_SCHEMA')
        fixed(payload[0]);integer(payload[2],1,86400)
        try:pin_from(payload[1])
        except Exception:raise E('PROTOCOL_SCHEMA') from None
    elif action=='put':
        fixed(b[6]);fixed(payload)
        if b[5] is None:raise E('PROTOCOL_SCHEMA')
    elif action=='seal':
        fixed(b[6])
        if b[5] is None or payload is not None:raise E('PROTOCOL_SCHEMA')
    return cap

def make_command(p,seed,capability,action,operation,call,lease,payload):
    b={0:1,1:PROFILE,2:action,3:operation,4:capability,5:call,6:lease,7:payload};cap=_shape(b)
    if p.sign_public(seed)!=cap[4]:raise E('REQUEST_AUTH')
    return _signed(p,seed,'command',b,MAX_REQUEST)
def check_command(p,raw):
    b,o=_split(raw,MAX_REQUEST);cap=_shape(b);_verify(p,cap[4],o,'command');return b

def make_request(p,seed,hello,command):
    b=check_command(p,command);cap,_=split(b[4]);check_hello(p,cap[3],hello)
    if p.sign_public(seed)!=cap[4]:raise E('REQUEST_AUTH')
    return _signed(p,seed,'request',{0:1,1:PROFILE,2:digest(hello),3:command},MAX_REQUEST)
def check_request(p,public,hello,raw):
    check_hello(p,public,hello);b,o=_split(raw,MAX_REQUEST);keys(b,range(4));_version(b);fixed(b[2])
    c=check_command(p,b[3]);cap,_=split(c[4]);_verify(p,cap[4],o,'request')
    if b[2]!=digest(hello) or cap[3]!=public:raise E('REQUEST_SCOPE')
    return b[3]
def make_response(p,seed,hello,request,ok,value):
    if type(ok) is not bool or (not ok and (type(value) is not str or value not in ERRORS)):raise E('PROTOCOL_SCHEMA')
    return _signed(p,seed,'response',{0:1,1:PROFILE,2:digest(hello),3:digest(request),4:ok,5:value,6:False},MAX_RESPONSE)
def check_response(p,public,hello,request,raw):
    b,o=_split(raw,MAX_RESPONSE);keys(b,range(7));_version(b);fixed(b[2]);fixed(b[3])
    if type(b[4]) is not bool or b[6] is not False:raise E('PROTOCOL_SCHEMA')
    _verify(p,public,o,'response')
    if (b[2],b[3])!=(digest(hello),digest(request)):raise E('RESPONSE_SCOPE')
    if not b[4]:
        if type(b[5]) is not str or b[5] not in ERRORS:raise E('PROTOCOL_SCHEMA')
        raise E('REMOTE_'+b[5])
    return b[5]
def token_for(p,command):
    b=check_command(p,command);cap,_=split(b[4])
    if b[2]!='begin':raise E('PROTOCOL_SCHEMA')
    return hashed('keeper-upload-local/stage',[cap[3],cap[4],b[3]])
def progress_shape(v):
    keys(v,range(6));fixed(v[0]);integer(v[1],0,max(MAX_INDEX,MAX_OBJECT));integer(v[2],1,max(MAX_INDEX,MAX_OBJECT));fixed(v[3])
    if v[1]>v[2] or type(v[4]) is not bool or v[5] is not False:raise E('RESPONSE_TYPE')
    if v[4] and v[1]!=v[2]:raise E('RESPONSE_TYPE')
    return v
