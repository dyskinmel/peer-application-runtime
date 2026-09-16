"""Separate mutation listener, sharing one owner with the unchanged read server.

There is no worker pool or arbitrary dispatch. Selector framing, absolute I/O
limits, endpoint ownership and teardown come from the existing private service.
Synchronous storage is deliberately not claimed to have a hard execution budget.
"""
import secrets,selectors,time
from par_keeper_service.server import Server as ReadServer,Connection
from par_keeper_service.transport import peer_uid,frame
from .protocol import *

def safe_error(ex):
    c=getattr(ex,'code','')
    if c in ('OUTCOME_UNKNOWN','STORAGE_UNCERTAIN','RECOVERY_REQUIRED'):return 'OUTCOME_UNKNOWN'
    if c in ('CAPABILITY_SCOPE','STALE_AUTHORITY'):return 'STALE_AUTHORITY'
    if c in ('CAPACITY','LEASE_LIMIT','OPERATION_LIMIT','STAGING_CAPACITY'):return 'CAPACITY'
    if c in ('BUSY','SQLITE_BUSY','WRITER_BUSY','PINNED'):return 'BUSY'
    if c in ('STAGE_UNKNOWN','LEASE_UNKNOWN','LEASE_RELEASED','NOT_SEALED','INCOMPLETE','STAGE_INCOMPLETE','NOT_UPLOADING'):return 'UNAVAILABLE'
    if c in ('OBJECT_HASH','STAGING_PERMISSIONS','STAGING_CORRUPT','CORRUPT_STORE','UNSAFE_PATH','OBJECT_MISSING','OBJECT_LIMIT','STAGE_COMMITTED'):return 'DATA_INVALID'
    if c in ('PROTOCOL_SCHEMA','SIGNATURE','REQUEST_AUTH','REQUEST_SCOPE','METHOD_DENIED','FRAME_LIMIT','CAPABILITY_AUTH','CONTRACT_SCHEMA','INDEX_INVALID','INDEX_SCOPE','OBJECT_SCOPE','STAGE_SCOPE','LEASE_OWNER','OPERATION_CONFLICT','CHUNK_RANGE','CHUNK_OFFSET','CHUNK_CONFLICT','DURATION_DENIED','ALREADY_SEALED'):return 'REJECTED'
    return 'INTERNAL'

class Server(ReadServer):
    def __init__(self,keeper,spool,path,**kw):
        if spool.keeper is not keeper:raise E('OWNER_REQUIRED')
        self.spool=spool;super().__init__(keeper,path,**kw)
    def _accept(self):
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
                if ex.code=='PEER_IDENTITY':self.counts['bad_requests']+=1;continue
                raise
            except BaseException:self.connections.pop(s.fileno(),None);s.close();raise
    def _stamp(self,command):return self.spool.stamp(command)
    def _dispatch(self,c,raw):
        try:
            command=check_request(self.p,self.keeper.public,c.hello,raw);c.request=command
            result=self.spool.execute(command);c.guard=self._stamp(command)
            response=make_response(self.p,self.keeper._seed,c.hello,raw,True,result)
        except Exception as ex:
            c.guard=None;self.counts['bad_requests']+=1
            response=make_response(self.p,self.keeper._seed,c.hello,raw,False,safe_error(ex))
        c.incoming.clear();c.output=frame(response,MAX_RESPONSE);c.sent=0;c.phase='response'
        self.selector.modify(c.socket,selectors.EVENT_WRITE,c);self._peak()
