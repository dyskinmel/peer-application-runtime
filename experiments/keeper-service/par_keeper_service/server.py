"""Single-owner bounded selector adapter. No worker pool and no public mutations.

Each connection has a fixed total I/O deadline and exactly one signed request.
Storage/crypto calls are synchronous and bounded by existing local profiles; an
I/O deadline does NOT preempt a blocked filesystem call or hostile native code.
"""
from dataclasses import dataclass,field
import selectors,secrets,socket,struct,threading,time
from par_keeper.contract import authority_body,dump as keeper_dump
from .errors import ServiceError as E
from .protocol import *
from .transport import Endpoint,peer_uid,frame

STATUS_KEYS=frozenset(('state','received','expected','bad','reserved_bytes','generation',
 'recipient_validated','currently_network_reachable','automatic_gc','product_qualified',
 'reader_pins','gc_pending'))

STATUS_STATES=frozenset(('AWAITING_OBJECTS','BYTES_COMPLETE_UNSEALED','RETAINED_ACTIVE','EXPIRED_RETAINED','UNKNOWN_RETAINED','RELEASED_RETAINED','DEGRADED','GC_PENDING','RECLAIMED'))

def status_pack(value):
    if type(value) is not dict or not set(value)<=STATUS_KEYS or 'state' not in value:raise E('BACKEND_STATUS')
    pairs=[[k,v] for k,v in sorted(value.items())]
    status_unpack(pairs)
    return pairs

def status_unpack(value):
    if type(value) is not list or not value or len(value)>len(STATUS_KEYS):raise E('RESPONSE_TYPE')
    out={}
    for row in value:
        if type(row) is not list or len(row)!=2 or type(row[0]) is not str or row[0] not in STATUS_KEYS or row[0] in out:raise E('RESPONSE_TYPE')
        out[row[0]]=row[1]
    if not (STATUS_KEYS-{'gc_pending'})<=set(out):raise E('RESPONSE_TYPE')
    if type(out['state']) is not str or out['state'] not in STATUS_STATES or out.get('product_qualified') is not False or out.get('recipient_validated') is not False:raise E('RESPONSE_TYPE')
    for k in ('received','expected','bad','reserved_bytes','generation','reader_pins'):
        if k in out and (type(out[k]) is not int or out[k]<0):raise E('RESPONSE_TYPE')
    for k in ('automatic_gc','gc_pending'):
        if k in out and type(out[k]) is not bool:raise E('RESPONSE_TYPE')
    if out.get('currently_network_reachable') is not None:raise E('RESPONSE_TYPE')
    return out

def sanitized_error(exc):
    code=getattr(exc,'code','')
    if code in ('CLOSED','LEASE_UNKNOWN','LEASE_RELEASED','NOT_SEALED','INCOMPLETE','OBJECT_MISSING'):return 'UNAVAILABLE'
    if code in ('OBJECT_HASH','CORRUPT_STORE','CORRUPT_GC','CORRUPT_REPAIR','REPAIR_UNSAFE_FILE','UNSAFE_PATH','OBJECT_LIMIT'):return 'DATA_INVALID'
    if code in ('STALE_AUTHORITY','STORAGE_UNCERTAIN'):return 'STALE_AUTHORITY'
    if code in ('PINNED','WRITER_BUSY','SQLITE_BUSY','BUSY'):return 'BUSY'
    if code in ('CONTRACT_SCHEMA','CAPABILITY_AUTH','CAPABILITY_SCOPE','REQUEST_AUTH','REQUEST_SCOPE','METHOD_DENIED','INDEX_SCOPE','OBJECT_SCOPE','LEASE_OWNER','PROTOCOL_SCHEMA','FRAME_LIMIT'):return 'REQUEST_REJECTED'
    return 'INTERNAL'

@dataclass
class Connection:
    socket:object
    hello:bytes
    deadline:float
    phase:str='hello'
    output:bytes=field(default=b'',repr=False)
    sent:int=0
    incoming:bytearray=field(default_factory=bytearray,repr=False)
    want:int=4
    request:object=None
    guard:object=None
    pin:object=None

class Server:
    def __init__(self,keeper,path,*,max_connections=8,deadline_ms=5000,send_chunk=65536):
        integer(max_connections,1,32);integer(deadline_ms,50,30000);integer(send_chunk,1,65536)
        if keeper._closed or keeper._thread!=threading.get_ident():raise E('OWNER_REQUIRED')
        self.keeper=keeper;self.p=keeper.provider;self.max_connections=max_connections;self.deadline_ms=deadline_ms;self.send_chunk=send_chunk
        self._thread=threading.get_ident();self._boot=secrets.token_bytes(32);self.connections={};self.closed=False
        self.counts={k:0 for k in ('accepted','completed','dropped','expired','overload','bad_requests','authority_changed','peak_connections','peak_buffered_bytes')}
        self.selector=selectors.DefaultSelector();self.endpoint=None
        try:
            self.endpoint=Endpoint(path,max_connections);self.selector.register(self.endpoint.socket,selectors.EVENT_READ,None)
        except BaseException:self.close();raise
    def _owner(self):
        if self.closed:raise E('CLOSED')
        if threading.get_ident()!=self._thread:raise E('WRONG_THREAD')
    def _peak(self):
        self.counts['peak_connections']=max(self.counts['peak_connections'],len(self.connections))
        size=sum(len(c.output)+len(c.incoming) for c in self.connections.values())
        self.counts['peak_buffered_bytes']=max(self.counts['peak_buffered_bytes'],size)
    def _drop(self,c,*,completed=False):
        fd=c.socket.fileno()
        try:self.selector.unregister(c.socket)
        except Exception:pass
        c.socket.close();self.connections.pop(fd,None)
        if c.pin is not None:
            pin=c.pin;c.pin=None;pin.__exit__(None,None,None)
        c.output=b'';c.incoming.clear()
        self.counts['completed' if completed else 'dropped']+=1
    def _accept(self):
        # Bound accept work even under an endless same-UID connection flood.
        for _ in range(self.max_connections+1):
            try:s,_=self.endpoint.socket.accept()
            except BlockingIOError:return
            if len(self.connections)>=self.max_connections:
                self.counts['overload']+=1;s.close();continue
            try:
                peer_uid(s);s.setblocking(False)
                hello=make_hello(self.p,self.keeper._seed,self._boot,secrets.token_bytes(32),self.deadline_ms)
                c=Connection(s,hello,time.monotonic()+self.deadline_ms/1000,output=frame(hello,MAX_HELLO))
                self.connections[s.fileno()]=c;self.selector.register(s,selectors.EVENT_WRITE,c)
                self.counts['accepted']+=1;self._peak()
            except E as ex:
                self.connections.pop(s.fileno(),None);s.close()
                if ex.code=='PEER_IDENTITY':
                    self.counts['bad_requests']+=1;continue
                raise
            except BaseException:
                self.connections.pop(s.fileno(),None);s.close();raise
    def _stamp(self,request):
        k=self.keeper
        with k._operation():
            _,_,row=k._authorized(request.capability,request.call,request.action,request.lease,request.payload)
            if request.action!='status':k._serving(row)
            return keeper_dump(authority_body(k.authority)),row['generation'],row['state']
    def _dispatch(self,c,raw):
        try:
            req=check_request(self.p,self.keeper.public,c.hello,raw);c.request=req
            k=self.keeper
            if req.action=='get':
                pin=k.reader(req.lease,req.payload,req.capability,req.call);reader=pin.__enter__();c.pin=pin
                result=reader.read()
            elif req.action=='status':result=status_pack(k.status(req.lease,req.capability,req.call))
            elif req.action=='receipt':result=k.receipt(req.lease,req.capability,req.call)
            elif req.action=='challenge':result=k.challenge(req.lease,req.payload,req.capability,req.call)
            else:raise E('METHOD_DENIED')
            c.guard=self._stamp(req)
            response=make_response(self.p,k._seed,c.hello,raw,True,result)
        except Exception as ex:
            if c.pin is not None:
                pin=c.pin;c.pin=None;pin.__exit__(None,None,None)
            c.guard=None;self.counts['bad_requests']+=1
            response=make_response(self.p,self.keeper._seed,c.hello,raw,False,sanitized_error(ex))
        c.incoming.clear();c.output=frame(response,MAX_RESPONSE);c.sent=0;c.phase='response'
        self.selector.modify(c.socket,selectors.EVENT_WRITE,c);self._peak()
    def _read(self,c):
        data=c.socket.recv(c.want-len(c.incoming))
        if not data:self._drop(c);return
        c.incoming.extend(data)
        if len(c.incoming)!=c.want:return
        if c.want==4:
            n=struct.unpack('>I',c.incoming)[0]
            if not 1<=n<=MAX_REQUEST:raise E('FRAME_LIMIT')
            c.want=4+n;return
        self._dispatch(c,bytes(c.incoming[4:]))
    def _write(self,c):
        if c.phase=='response' and c.guard is not None:
            try:
                if self._stamp(c.request)!=c.guard:raise E('AUTHORITY_CHANGED')
            except Exception:
                self.counts['authority_changed']+=1;self._drop(c);return
        chunk=len(c.output) if c.phase=='hello' else self.send_chunk
        n=c.socket.send(memoryview(c.output)[c.sent:c.sent+chunk])
        if n==0:self._drop(c);return
        c.sent+=n
        if c.sent<len(c.output):return
        if c.phase=='response':self._drop(c,completed=True);return
        c.output=b'';c.sent=0;c.phase='request'
        self.selector.modify(c.socket,selectors.EVENT_READ,c)
    def poll(self,timeout=.05):
        self._owner()
        if type(timeout) not in (int,float) or not 0<=timeout<=1:raise E('PROTOCOL_SCHEMA')
        now=time.monotonic()
        for c in list(self.connections.values()):
            if now>=c.deadline:self.counts['expired']+=1;self._drop(c)
        if self.connections:timeout=min(timeout,max(0,min(c.deadline for c in self.connections.values())-time.monotonic()))
        for key,mask in self.selector.select(timeout):
            if key.data is None:self._accept();continue
            c=key.data
            if c.socket.fileno()<0:continue
            if time.monotonic()>=c.deadline:self.counts['expired']+=1;self._drop(c);continue
            try:
                if mask&selectors.EVENT_READ:self._read(c)
                elif mask&selectors.EVENT_WRITE:self._write(c)
            except BlockingIOError:continue
            except (OSError,E):
                if c.socket.fileno()>=0:self._drop(c)
        self._peak()
    def diagnostics(self):
        self._owner()
        return dict(self.counts,active_connections=len(self.connections),max_connections=self.max_connections,
            product_qualified=False,public_listener=False,transport='AF_UNIX_PRIVATE_LINUX',
            native_storage_preemption=False)
    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        for c in list(self.connections.values()):self._drop(c)
        self.selector.close()
        if self.endpoint is not None:self.endpoint.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
