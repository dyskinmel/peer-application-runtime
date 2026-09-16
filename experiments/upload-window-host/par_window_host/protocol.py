"""Generation-bound private IPC. No wire fallback or management dispatch.

The trusted window grant travels out of band. All data commands are signed by
its subject and scoped to that window; the connection signature adds freshness.
"""
from par_crypto.primitives import domain, hashed
from par_keeper.contract import split
from par_keeper_upload import protocol as u
from par_upload_window import contract as w

E=u.E
PROFILE='upload-window-host-local-v1'
MAX_HELLO=4096
MAX_REQUEST=65536
MAX_RESPONSE=1048576
METHODS=u.METHODS
ERRORS=u.ERRORS | frozenset(('STALE_WINDOW',))
fixed, integer, keys, dump, load = u.fixed,u.integer,u.keys,u.dump,u.load

def digest(raw):
    if type(raw) is not bytes:raise E('PROTOCOL_SCHEMA')
    return hashed('upload-window-host-local/bytes',[raw])

def _signed(p,seed,label,body,maximum):
    raw=dump(body,maximum)
    return dump({0:raw,1:p.sign(seed,domain('upload-window-host-local/'+label,[raw]))},maximum)

def _split(raw,maximum):
    o=load(raw,maximum);keys(o,(0,1));fixed(o[1],64)
    if type(o[0]) is not bytes:raise E('PROTOCOL_SCHEMA')
    return load(o[0],maximum),o

def _verify(p,public,o,label):
    fixed(public)
    try:p.verify(public,domain('upload-window-host-local/'+label,[o[0]]),o[1])
    except Exception:raise E('SIGNATURE') from None

def _version(b):
    integer(b[0],1,1)
    if b[1]!=PROFILE:raise E('PROTOCOL_SCHEMA')

def make_hello(p,seed,*,store,window,phase,boot,challenge,deadline_ms):
    fixed(seed);fixed(store);fixed(boot);fixed(challenge);integer(deadline_ms,50,30000)
    grant=w.check_window(p,window)
    if (grant[3],grant[4])!=(p.sign_public(seed),store):raise E('WINDOW_SCOPE')
    if type(phase) is not str or phase not in ('OPEN','CLOSED','CLEANED'):raise E('PROTOCOL_SCHEMA')
    body={0:1,1:PROFILE,2:p.sign_public(seed),3:boot,4:challenge,5:deadline_ms,
          6:MAX_REQUEST,7:MAX_RESPONSE,8:store,9:w.digest(window),10:grant[5],11:phase}
    return _signed(p,seed,'hello',body,MAX_HELLO)

def check_hello(p,public,store,window,raw):
    fixed(public);fixed(store);grant=w.check_window(p,window)
    b,o=_split(raw,MAX_HELLO);keys(b,range(12));_version(b)
    for k in (2,3,4,8,9):fixed(b[k])
    integer(b[5],50,30000);integer(b[6],MAX_REQUEST,MAX_REQUEST);integer(b[7],MAX_RESPONSE,MAX_RESPONSE)
    integer(b[10],1,w.MAX_WINDOWS)
    if type(b[11]) is not str or b[11] not in ('OPEN','CLOSED','CLEANED'):raise E('PROTOCOL_SCHEMA')
    _verify(p,public,o,'hello')
    if (grant[3],grant[4],b[2],b[8],b[9],b[10])!=(public,store,public,store,w.digest(window),grant[5]):raise E('WINDOW_SCOPE')
    return b

def data_command(p,window,raw):
    if type(raw) is not bytes or len(raw)>MAX_REQUEST:raise E('FRAME_LIMIT')
    outer=w.check_command(p,window,raw)
    if outer[3]!='execute':raise E('METHOD_DENIED')
    inner=u.check_command(p,outer[4])
    if inner[2] not in METHODS:raise E('METHOD_DENIED')
    return outer,inner

def make_request(p,seed,hello,window,command):
    outer,inner=data_command(p,window,command);cap,_=split(inner[4]);grant=w.check_window(p,window)
    b=check_hello(p,cap[3],grant[4],window,hello)
    if b[11]!='OPEN':raise E('WINDOW_CLOSED')
    if p.sign_public(seed)!=outer[5]:raise E('REQUEST_AUTH')
    return _signed(p,seed,'request',{0:1,1:PROFILE,2:digest(hello),3:command},MAX_REQUEST)

def check_request(p,public,store,window,hello,raw):
    h=check_hello(p,public,store,window,hello)
    if h[11]!='OPEN':raise E('WINDOW_CLOSED')
    b,o=_split(raw,MAX_REQUEST);keys(b,range(4));_version(b);fixed(b[2])
    outer,inner=data_command(p,window,b[3]);cap,_=split(inner[4])
    _verify(p,outer[5],o,'request')
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
