"""Signed local replay-window candidate; no clock-based admission or wire fallback."""
from par_crypto.primitives import domain, hashed
from par_keeper.contract import authority_body, authority_from, split
from par_keeper_upload import protocol as u
from par_keeper_upload_retire import contract as r
E = u.E
PROFILE = 'upload-replay-window-local-v1'
MAX_WINDOWS = 64
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_ARCHIVES = 64 * 1024 * 1024
MAX_CONTROL = 262144
fixed, integer, keys = u.fixed, u.integer, u.keys

def dump(v, maximum=MAX_CONTROL): return u.dump(v, maximum)
def load(b, maximum=MAX_CONTROL): return u.load(b, maximum)
def digest(b):
    if type(b) is not bytes or not b or len(b) > MAX_ARCHIVE: raise E('WINDOW_SCHEMA')
    import hashlib
    return hashed('upload-replay-window-local/bytes', [len(b), hashlib.sha256(b).digest()])
def signed(p, seed, label, body, maximum=MAX_CONTROL):
    raw = dump(body, maximum)
    return dump({0:raw, 1:p.sign(seed, domain('upload-replay-window-local/'+label,[raw]))}, maximum)
def unpack(raw, maximum=MAX_CONTROL):
    outer=load(raw,maximum);keys(outer,(0,1));fixed(outer[1],64)
    if type(outer[0]) is not bytes: raise E('WINDOW_SCHEMA')
    return load(outer[0],maximum), outer

def verified(p, raw, label, public, maximum=MAX_CONTROL):
    b,o=unpack(raw,maximum);fixed(public)
    try:p.verify(public,domain('upload-replay-window-local/'+label,[o[0]]),o[1])
    except Exception:raise E('WINDOW_SIGNATURE') from None
    return b

def version(b):
    integer(b[0],1,1)
    if b[1]!=PROFILE:raise E('WINDOW_SCHEMA')

def check_window(p, raw):
    b,_=unpack(raw);keys(b,range(8));version(b)
    try:a=authority_from(b[2])
    except Exception:raise E('WINDOW_SCHEMA') from None
    for i in (3,4,6):fixed(b[i])
    integer(b[5],1,MAX_WINDOWS)
    if b[5]==1:
        if b[7] is not None:raise E('WINDOW_ORDER')
    else:fixed(b[7])
    verified(p,raw,'open',a.issuer);return b

def make_window(p, seed, authority, keeper, store, sequence, nonce, previous=None):
    if p.sign_public(seed)!=authority.issuer:raise E('WINDOW_ISSUER')
    raw=signed(p,seed,'open',{0:1,1:PROFILE,2:authority_body(authority),3:keeper,4:store,5:sequence,6:nonce,7:previous})
    check_window(p,raw);return raw

def _subject(p, kind, inner):
    if kind=='execute':
        b=u.check_command(p,inner);cap=split(b[4])[0];r.origin(p,inner) if b[2]=='begin' else None
        return cap[4],cap[3],cap[2]
    if kind in ('retire','rebind'):
        g=r.inspect_request(p,inner)[2];return g[4],g[3],g[2]
    raise E('WINDOW_METHOD')

def check_command(p, window, raw):
    w=check_window(p,window);b,_=unpack(raw);keys(b,range(6));version(b)
    fixed(b[2]);fixed(b[5])
    if type(b[3]) is not str:raise E('WINDOW_SCHEMA')
    subject,keeper,authority=_subject(p,b[3],b[4])
    if (b[2],b[5],keeper,authority[:2])!=(digest(window),subject,w[3],w[2][:2]):raise E('WINDOW_SCOPE')
    verified(p,raw,'command',subject);return b

def wrap_command(p, seed, window, kind, inner):
    w=check_window(p,window);subject,_,_=_subject(p,kind,inner)
    if p.sign_public(seed)!=subject:raise E('WINDOW_SUBJECT')
    raw=signed(p,seed,'command',{0:1,1:PROFILE,2:digest(window),3:kind,4:inner,5:subject})
    check_command(p,window,raw);return raw

def check_close(p, window, raw, archive_hash=None):
    w=check_window(p,window);b,_=unpack(raw);keys(b,range(8));version(b)
    try:a=authority_from(b[2])
    except Exception:raise E('WINDOW_SCHEMA') from None
    for i in (3,4,6,7):fixed(b[i])
    integer(b[5],1,MAX_WINDOWS);r._authority_order(w[2],b[2])
    if (b[3],b[4],b[5])!=(digest(window),w[4],w[5]):raise E('WINDOW_SCOPE')
    if archive_hash is not None and b[6]!=archive_hash:raise E('ARCHIVE_CHANGED')
    verified(p,raw,'close',a.issuer);return b

def approve_close(p, seed, authority, window, archive, operation):
    w=check_window(p,window);check_archive(p,archive,window)
    if p.sign_public(seed)!=authority.issuer:raise E('WINDOW_ISSUER')
    raw=signed(p,seed,'close',{0:1,1:PROFILE,2:authority_body(authority),3:digest(window),4:w[4],5:w[5],6:digest(archive),7:operation})
    check_close(p,window,raw);return raw

def check_archive(p, raw, window):
    """Verify exact grouped terminal records without opening or mutating a Store."""
    import re, hashlib
    w=check_window(p,window)
    if type(raw) is not bytes or not 11<=len(raw)<=MAX_ARCHIVE or raw[:7]!=b'PARWA1\x00':raise E('ARCHIVE_SCHEMA')
    n=int.from_bytes(raw[7:11],'big')
    if not 1<=n<=900000 or 11+n>len(raw):raise E('ARCHIVE_SCHEMA')
    b=verified(p,raw[11:11+n],'archive',w[3],900000)
    keys(b,range(7));version(b);integer(b[4],1,MAX_WINDOWS)
    if type(b[5]) is not list or len(b[5])>3072:raise E('ARCHIVE_SCHEMA')
    entries=[];offset=11+n
    for e in b[5]:
        if type(e) is not list or len(e)!=5:raise E('ARCHIVE_SCHEMA')
        integer(e[1],1,MAX_CONTROL)
        if offset+e[1]>len(raw):raise E('ARCHIVE_SCHEMA')
        entries.append(e+[raw[offset:offset+e[1]]]);offset+=e[1]
    if offset!=len(raw):raise E('ARCHIVE_SCHEMA')
    b[5]=entries
    if (b[2],b[3],b[4])!=(digest(window),w[4],w[5]):raise E('WINDOW_SCOPE')
    integer(b[6],0,1024)
    if type(b[5]) is not list or len(b[5])>3072:raise E('ARCHIVE_SCHEMA')
    grouped={};names=[]
    for entry in b[5]:
        if type(entry) is not list or len(entry)!=6:raise E('ARCHIVE_SCHEMA')
        name,size,sha,dev,ino,data=entry
        if type(name) is not str or not re.fullmatch(r'(live/[0-9a-f]{64}\.(cbor|retirement)|bindings/[0-9a-f]{64}\.bound)',name):raise E('ARCHIVE_PATH')
        integer(size,1,MAX_CONTROL);fixed(sha);integer(dev,0,2**64-1);integer(ino,0,2**64-1)
        if type(data) is not bytes or len(data)!=size or hashlib.sha256(data).digest()!=sha:raise E('ARCHIVE_HASH')
        token=name.split('/')[-1].split('.')[0];ext=name.rsplit('.',1)[1]
        if ext in grouped.setdefault(token,{}):raise E('ARCHIVE_DUPLICATE')
        grouped[token][ext]=data;names.append(name)
    if names!=sorted(set(names)) or len(grouped)!=b[6]:raise E('ARCHIVE_SET')
    for token,files in grouped.items():
        if not {'bound','cbor'}<=files.keys():raise E('ARCHIVE_SET')
        bound=check_command(p,window,files['bound'])
        if bound[3]!='execute':raise E('ARCHIVE_SET')
        origin,cap=r.origin(p,bound[4]);t=bytes.fromhex(token)
        m=u.load(files['cbor'],MAX_CONTROL);keys(m,range(8));integer(m[0],1,1)
        if origin[2]!='begin' or (m[1],m[2])!=(t,bound[4]) or u.token_for(p,bound[4])!=t:raise E('ARCHIVE_ORIGIN')
        integer(m[3],0,origin[7][2]);fixed(m[4])
        if m[5]=='committed':
            if set(files)!= {'bound','cbor'}:raise E('ARCHIVE_SET')
            f=u.check_command(p,m[6]);fixed(m[7])
            if (m[3],m[4])!=(origin[7][2],origin[7][3]):raise E('ARCHIVE_TERMINAL')
            action='reserve' if origin[7][0]=='index' else 'put'
            if f[2]!=action or (f[4],f[6])!=(origin[4],origin[6]):raise E('ARCHIVE_TERMINAL')
            if (f[7][0] if action=='reserve' else f[7])!=t:raise E('ARCHIVE_TERMINAL')
            if action=='put' and (m[7]!=origin[7][1] or f[5]!=origin[5]):raise E('ARCHIVE_TERMINAL')
        elif m[5]=='active':
            if set(files)!= {'bound','cbor','retirement'} or m[6] is not None or m[7] is not None:raise E('ARCHIVE_TERMINAL')
            j=r.verified(p,files['retirement'],'journal',w[3]);keys(j,range(10));r.version(j)
            if (j[2],j[3],j[4],j[6],j[8])!=(w[3],t,r.digest(files['cbor']),'TOMBSTONED',origin[7][2]):raise E('ARCHIVE_TERMINAL')
            if type(j[5]) is not list or not 1<=len(j[5])<=r.MAX_REBINDS:raise E('ARCHIVE_TERMINAL')
            previous=None;seen=set()
            for q in j[5]:
                g=r.check_request(p,q,m[2],w[3])[2];rid=r.request_id(p,q)
                if rid in seen:raise E('ARCHIVE_TERMINAL')
                if previous is not None:
                    r._authority_order(previous,g[2])
                    if g[2][3]<=previous[3]:raise E('ARCHIVE_TERMINAL')
                previous=g[2];seen.add(rid)
            if type(j[7]) is not list or len(j[7])!=4 or j[7][2:]!=[m[3],m[4]]:raise E('ARCHIVE_TERMINAL')
            for value in j[7][:3]:integer(value,0,2**64-1)
            body=r.verified(p,j[9],'receipt',w[3])
            expected={0:1,1:r.PROFILE,2:w[3],3:t,4:r.digest(j[5][-1]),5:j[8],6:j[7][2],7:'TOMBSTONED',8:False,9:False,10:False}
            if r.dump(body)!=r.dump(expected):raise E('ARCHIVE_TERMINAL')
        else:raise E('ARCHIVE_TERMINAL')
    return b


def sign_archive(p, seed, body):
    """Framed bounded audit container; each signed manifest stays below wire limits."""
    b=dict(body);entries=body[5];b[5]=[e[:5] for e in entries]
    header=signed(p,seed,'archive',b,900000)
    raw=b'PARWA1\x00'+len(header).to_bytes(4,'big')+header+b''.join(e[5] for e in entries)
    if len(raw)>MAX_ARCHIVE:raise E('ARCHIVE_CAPACITY')
    return raw
