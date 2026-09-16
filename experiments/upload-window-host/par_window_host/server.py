"""Single-owner selector service. The replay gateway is the only write dispatch.

Local management can run on the owner thread, but is never exposed over this
socket. Read service is unchanged and can share the same owner/keeper.
"""
import secrets, selectors, time
from par_keeper_service.server import Server as ReadServer, Connection
from par_keeper_service.transport import peer_uid,frame
from par_keeper_upload.server import safe_error as legacy_error
from par_upload_window import ReplaySpool
from .protocol import *

def safe_error(exc):
    code=getattr(exc,'code','')
    if code in ('WINDOW_CLOSED','WINDOW_CLOSE_PREPARED','WINDOW_SCOPE','WINDOW_ORDER','WINDOW_NOT_CLOSED','WINDOW_ALREADY_OPEN'):return 'STALE_WINDOW'
    if code in ('ARCHIVE_CAPACITY','WINDOW_LIMIT','RETIREMENT_LIMIT'):return 'CAPACITY'
    if code in ('WINDOW_SIGNATURE','WINDOW_SUBJECT','WINDOW_METHOD','WINDOW_SCHEMA','RETIREMENT_AUTH','RETIRED','RETIREMENT_PENDING'):return 'REJECTED'
    if code in ('WINDOW_STATE_CHANGED','WINDOW_RECORD_CHANGED','WINDOW_DATA_REAPPEARED','ARCHIVE_CHANGED','ARCHIVE_MISSING'):return 'DATA_INVALID'
    return legacy_error(exc)

class Server(ReadServer):
    def __init__(self,keeper,gateway,path,**kw):
        if type(gateway) is not ReplaySpool or gateway.keeper is not keeper:raise E('GATEWAY_REQUIRED')
        gateway._enter()
        if gateway.window is None:raise E('WINDOW_REQUIRED')
        self.gateway=gateway
        super().__init__(keeper,path,**kw)
    def _accept(self):
        for _ in range(self.max_connections+1):
            try:s,_=self.endpoint.socket.accept()
            except BlockingIOError:return
            if len(self.connections)>=self.max_connections:
                self.counts['overload']+=1;s.close();continue
            try:
                peer_uid(s);s.setblocking(False);self.gateway._enter()
                hello=make_hello(self.p,self.keeper._seed,store=self.gateway.store_id,window=self.gateway.window,
                    phase=self.gateway.phase,boot=self._boot,challenge=secrets.token_bytes(32),deadline_ms=self.deadline_ms)
                c=Connection(s,hello,time.monotonic()+self.deadline_ms/1000,output=frame(hello,MAX_HELLO))
                self.connections[s.fileno()]=c;self.selector.register(s,selectors.EVENT_WRITE,c)
                self.counts['accepted']+=1;self._peak()
            except E as ex:
                self.connections.pop(s.fileno(),None);s.close()
                if ex.code=='PEER_IDENTITY':self.counts['bad_requests']+=1;continue
                raise
            except BaseException:self.connections.pop(s.fileno(),None);s.close();raise
    def _stamp(self,command):return self.gateway.stamp(command)
    def _dispatch(self,c,raw):
        try:
            self.gateway._enter()
            command=check_request(self.p,self.keeper.public,self.gateway.store_id,self.gateway.window,c.hello,raw)
            c.request=command
            result=self.gateway.execute(command)
            c.guard=self._stamp(command)
            response=make_response(self.p,self.keeper._seed,c.hello,raw,True,result)
        except Exception as ex:
            c.guard=None;self.counts['bad_requests']+=1
            response=make_response(self.p,self.keeper._seed,c.hello,raw,False,safe_error(ex))
        c.incoming.clear();c.output=frame(response,MAX_RESPONSE);c.sent=0;c.phase='response'
        self.selector.modify(c.socket,selectors.EVENT_WRITE,c);self._peak()
