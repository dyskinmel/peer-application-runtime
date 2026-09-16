"""One request per signed challenge. Candidate IPC format, not PAR v1 wire.

Keeper trust is pinned by the caller. The wrapper proves request possession and
connection binding; only the Keeper's existing current-authority check grants
access. A self-described capability issuer is never an authority root here.
"""
from dataclasses import dataclass,field
from par_wire.codec import encode,decode
from par_crypto.primitives import domain,hashed
from par_keeper.contract import split,capability_shape,call_shape
from .errors import ServiceError as E

PROFILE='keeper-service-local-v1'
MAX_HELLO=4096
MAX_REQUEST=65536
MAX_RESPONSE=1048576
METHODS=frozenset(('get','status','receipt','challenge'))
REMOTE_ERRORS=frozenset(('REQUEST_REJECTED','UNAVAILABLE','DATA_INVALID','STALE_AUTHORITY','INTERNAL','BUSY'))

def fixed(v,n=32):
    if type(v) is not bytes or len(v)!=n:raise E('PROTOCOL_SCHEMA')
def integer(v,lo,hi):
    if type(v) is not int or not lo<=v<=hi:raise E('PROTOCOL_SCHEMA')
def keys(v,expected):
    if type(v) is not dict or any(type(k) is not int for k in v) or set(v)!=set(expected):raise E('PROTOCOL_SCHEMA')
def dump(v,maximum):
    try:return encode(v,max_bytes=maximum)
    except Exception:raise E('PROTOCOL_SCHEMA') from None
def load(raw,maximum):
    if type(raw) is not bytes:raise E('PROTOCOL_SCHEMA')
    if not 1<=len(raw)<=maximum:raise E('FRAME_LIMIT')
    try:
        value=decode(raw,max_bytes=maximum)
        if encode(value,max_bytes=maximum)!=raw:raise ValueError()
        return value
    except Exception:raise E('PROTOCOL_SCHEMA') from None

def _sign(p,seed,label,body,maximum):
    raw=dump(body,maximum)
    return dump({0:raw,1:p.sign(seed,domain('keeper-service-local/'+label,[raw]))},maximum)

def _split(raw,maximum):
    o=load(raw,maximum);keys(o,(0,1));fixed(o[1],64)
    return load(o[0],maximum),o

def _verify(p,public,o,label,code):
    fixed(public)
    try:p.verify(public,domain('keeper-service-local/'+label,[o[0]]),o[1])
    except Exception:raise E(code) from None

def digest(raw):
    if type(raw) is not bytes:raise E('PROTOCOL_SCHEMA')
    return hashed('keeper-service-local/bytes',[raw])

def _version(b):
    integer(b[0],1,1)
    if b[1]!=PROFILE:raise E('PROTOCOL_SCHEMA')

def make_hello(p,seed,boot,challenge,deadline_ms):
    fixed(seed);fixed(boot);fixed(challenge);integer(deadline_ms,50,30000)
    return _sign(p,seed,'hello-sign',{0:1,1:PROFILE,2:p.sign_public(seed),3:boot,4:challenge,5:deadline_ms,6:MAX_REQUEST,7:MAX_RESPONSE},MAX_HELLO)

def check_hello(p,public,raw):
    b,o=_split(raw,MAX_HELLO);keys(b,range(8));_version(b)
    for k in (2,3,4):fixed(b[k])
    integer(b[5],50,30000);integer(b[6],MAX_REQUEST,MAX_REQUEST);integer(b[7],MAX_RESPONSE,MAX_RESPONSE)
    _verify(p,public,o,'hello-sign','HELLO_AUTH')
    if b[2]!=public:raise E('HELLO_AUTH')
    return b

@dataclass(frozen=True)
class Request:
    action:str
    lease:bytes
    payload:bytes|None
    capability:bytes=field(repr=False)
    call:bytes=field(repr=False)
    subject:bytes

def _request_shape(b):
    keys(b,range(8));_version(b);fixed(b[2]);fixed(b[6])
    if type(b[5]) is not str or b[5] not in METHODS:raise E('METHOD_DENIED')
    if b[5] in ('get','challenge'):fixed(b[7])
    elif b[7] is not None:raise E('PROTOCOL_SCHEMA')
    try:
        cap,_=split(b[3]);capability_shape(cap)
        call,_=split(b[4]);call_shape(call)
    except Exception:raise E('PROTOCOL_SCHEMA') from None
    if cap[4]!=call[4] or call[5]!=b[5] or call[6]!=b[6]:raise E('REQUEST_SCOPE')
    return cap

def make_request(p,seed,hello,capability,call,action,lease,payload=None):
    body={0:1,1:PROFILE,2:digest(hello),3:capability,4:call,5:action,6:lease,7:payload}
    cap=_request_shape(body)
    if p.sign_public(seed)!=cap[4]:raise E('REQUEST_AUTH')
    check_hello(p,cap[3],hello)
    return _sign(p,seed,'request-sign',body,MAX_REQUEST)

def check_request(p,public,hello,raw):
    check_hello(p,public,hello)
    b,o=_split(raw,MAX_REQUEST);cap=_request_shape(b)
    _verify(p,cap[4],o,'request-sign','REQUEST_AUTH')
    if b[2]!=digest(hello) or cap[3]!=public:raise E('REQUEST_SCOPE')
    return Request(b[5],b[6],b[7],b[3],b[4],cap[4])

def make_response(p,seed,hello,request,ok,value):
    if type(ok) is not bool:raise E('PROTOCOL_SCHEMA')
    if not ok and (type(value) is not str or value not in REMOTE_ERRORS):raise E('PROTOCOL_SCHEMA')
    return _sign(p,seed,'response-sign',{0:1,1:PROFILE,2:digest(hello),3:digest(request),4:ok,5:value,6:False},MAX_RESPONSE)

def check_response(p,public,hello,request,raw):
    b,o=_split(raw,MAX_RESPONSE);keys(b,range(7));_version(b);fixed(b[2]);fixed(b[3])
    if type(b[4]) is not bool or b[6] is not False:raise E('PROTOCOL_SCHEMA')
    _verify(p,public,o,'response-sign','RESPONSE_AUTH')
    if (b[2],b[3])!=(digest(hello),digest(request)):raise E('RESPONSE_SCOPE')
    if not b[4]:
        if type(b[5]) is not str or b[5] not in REMOTE_ERRORS:raise E('PROTOCOL_SCHEMA')
        raise E('REMOTE_'+b[5])
    return b[5]
