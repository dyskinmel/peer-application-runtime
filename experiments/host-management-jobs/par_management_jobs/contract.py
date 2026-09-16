"""Versioned private job journal. Keeper signatures are NOT management grants."""
import hashlib
from par_keeper_upload import protocol as u
from par_keeper.contract import authority_from
from par_crypto.primitives import domain
E=u.E
PROFILE='host-management-jobs-local-v1'
ACTIONS=('retire','close','compact','open')
STATES=('QUEUED','VALIDATED','PREPARED','EXECUTING','OUTCOME_UNKNOWN','RETRY_READY','SUCCEEDED','CANCELLED')
CANCELLABLE=frozenset(('QUEUED','VALIDATED','PREPARED'))
EDGES={None:('QUEUED',),'QUEUED':('VALIDATED','CANCELLED'),
       'VALIDATED':('PREPARED','CANCELLED'),'PREPARED':('EXECUTING','CANCELLED'),
       'EXECUTING':('OUTCOME_UNKNOWN','RETRY_READY','SUCCEEDED'),
       'OUTCOME_UNKNOWN':('RETRY_READY','SUCCEEDED'),
       'RETRY_READY':('EXECUTING','SUCCEEDED'),'SUCCEEDED':(),'CANCELLED':()}
MAX_HEADER=524288
MAX_ARCHIVE=16*1024*1024
MAX_FILE=MAX_HEADER+MAX_ARCHIVE+12
MAX_JOBS=32
MAX_TOTAL=64*1024*1024
MAX_EVENTS=32
MAGIC=b'PARJOB1\x00'

def fail():raise E('JOB_SCHEMA')
def fixed(x):
    if type(x) is not bytes or len(x)!=32:fail()
def integer(x,lo,hi):
    if type(x) is not int or not lo<=x<=hi:fail()
def keys(x,ks):
    if type(x) is not dict or any(type(k) is not int for k in x) or set(x)!=set(ks):fail()
def sha(x):
    if type(x) is not bytes:fail()
    return hashlib.sha256(x).digest()
def dump(x):return u.dump(x,MAX_HEADER)
def load(x):return u.load(x,MAX_HEADER)
def arguments(jid,action,command,archive):
    fixed(jid)
    if type(action) is not str or action not in ACTIONS:raise E('JOB_METHOD')
    if action=='compact':
        if command is not None or archive is not None:fail()
    else:
        if type(command) is not bytes or not 1<=len(command)<=262144:fail()
        if action=='close':
            if type(archive) is not bytes or not 1<=len(archive)<=MAX_ARCHIVE:fail()
        elif archive is not None:fail()

def shape(b,archive):
    keys(b,range(14));integer(b[0],1,1)
    if b[1]!=PROFILE:fail()
    for i in (2,3,4):fixed(b[i])
    arguments(b[4],b[5],b[6],archive if b[5]=='close' else None)
    if b[5]!='close' and archive:fail()
    integer(b[8],0,MAX_ARCHIVE)
    if (b[7],b[8])!=((sha(archive),len(archive)) if archive else (None,0)):fail()
    authority_from(b[9]);keys(b[10],range(4));fixed(b[10][0]);integer(b[10][1],0,64)
    if b[10][0]!=b[3] or b[11] not in ('EMPTY','OPEN','CLOSED','CLEANED'):fail()
    if b[10][1]==0:
        if b[12] is not None or b[10][2] is not None or b[10][3] is not None:fail()
    else:
        fixed(b[10][2])
        if b[10][3] is not None:fixed(b[10][3])
        if type(b[12]) is not bytes:fail()
    history=b[13]
    if type(history) is not list or not 1<=len(history)<=MAX_EVENTS:fail()
    last=None
    for i,event in enumerate(history):
        keys(event,range(4));integer(event[0],i,i)
        if type(event[1]) is not str or event[1] not in EDGES[last]:raise E('JOB_TRANSITION')
        if event[1]=='SUCCEEDED':
            if type(event[2]) is not bytes or not 1<=len(event[2])<=262144:fail()
            fixed(event[3])
        elif event[2] is not None or event[3] is not None:fail()
        last=event[1]
    return b

def pack(p,seed,b,archive=b''):
    shape(b,archive);raw=dump(b)
    head=dump({0:raw,1:p.sign(seed,domain('management-jobs-local/journal',[raw]))})
    return MAGIC+len(head).to_bytes(4,'big')+head+archive

def unpack(p,public,raw):
    fixed(public)
    if type(raw) is not bytes or not 13<=len(raw)<=MAX_FILE or raw[:8]!=MAGIC:fail()
    n=int.from_bytes(raw[8:12],'big');integer(n,1,MAX_HEADER)
    if 12+n>len(raw):fail()
    head=load(raw[12:12+n]);keys(head,(0,1))
    if type(head[0]) is not bytes or type(head[1]) is not bytes or len(head[1])!=64:fail()
    try:p.verify(public,domain('management-jobs-local/journal',[head[0]]),head[1])
    except Exception:raise E('JOB_SIGNATURE') from None
    b=load(head[0]);archive=raw[12+n:];shape(b,archive)
    if b[2]!=public:raise E('JOB_SCOPE')
    return b,archive

def input_equal(b,action,command,archive):
    return (b[5],b[6],b[7],b[8])==(action,command,sha(archive) if archive else None,len(archive) if archive else 0)

def intent(b):return sha(dump([b[i] for i in (2,3,5,6,7,8,10,11,12)]))
