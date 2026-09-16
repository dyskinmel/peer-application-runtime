"""Private Linux bounded control endpoint; no data pin and no generic methods."""
import os,selectors,secrets,socket,threading,time
from par_keeper_service.server import Server as BaseServer, Connection
from par_keeper_service.transport import peer_uid,frame
from . import protocol as c
E=c.E
class Server(BaseServer):
    def __init__(self,controller,path,*,max_connections=4,deadline_ms=5000,send_chunk=65536):
        c.integer(max_connections,1,8)
        self.controller=controller;self.pid=os.getpid()
        # Endpoint checks private directory, permissions, UID and exclusive lock.
        super().__init__(controller.host.keeper,path,max_connections=max_connections,deadline_ms=deadline_ms,send_chunk=send_chunk)
    def _owner(self):
        if self.pid!=os.getpid():raise E('CONTROL_OWNER')
        super()._owner();self.controller.host._guard()
    def _accept(self):
        for _ in range(self.max_connections+1):
            try:s,_=self.endpoint.socket.accept()
            except BlockingIOError:return
            if len(self.connections)>=self.max_connections:
                self.counts['overload']+=1;s.close();continue
            try:
                peer_uid(s);s.setblocking(False)
                public,rev=self.controller.policy()
                hi=c.make_hello(self.p,self.keeper._seed,store=self.controller.host.gateway.store_id,controller=public,revision=rev,boot=self._boot,challenge=secrets.token_bytes(32),deadline_ms=self.deadline_ms)
                conn=Connection(s,hi,time.monotonic()+self.deadline_ms/1000,output=frame(hi,c.MAX_HELLO));conn.guard=(public,rev)
                self.connections[s.fileno()]=conn;self.selector.register(s,selectors.EVENT_WRITE,conn);self.counts['accepted']+=1
            except E:
                self.connections.pop(s.fileno(),None);s.close();self.counts['bad_requests']+=1
            except BaseException:
                self.connections.pop(s.fileno(),None);s.close();raise
    def _read(self,conn):
        b=conn.socket.recv(min(65536,conn.want-len(conn.incoming)))
        if not b:self._drop(conn);return
        conn.incoming.extend(b)
        if len(conn.incoming)==4 and conn.want==4:
            n=int.from_bytes(conn.incoming,'big')
            if not 1<=n<=c.MAX_REQUEST:raise E('FRAME_LIMIT')
            conn.want=4+n
        if len(conn.incoming)==conn.want:
            request=bytes(conn.incoming[4:]);conn.request=request
            ok=False;value='REJECTED'
            try:
                public,rev=self.controller.policy()
                if public is None or (public,rev)!=conn.guard:raise E('STALE_CONTROLLER')
                i=c.check_request(self.p,self.keeper.public,self.controller.host.gateway.store_id,public,rev,conn.hello,request)
                value=self.controller.execute(i.raw);ok=True
            except Exception as exc:
                self.counts['bad_requests']+=1
                code=getattr(exc,'code','')
                if self.controller.journal.poison:
                    self.controller.host._hold('CONTROL_REOPEN_REQUIRED');value='CONTROL_UNCERTAIN'
                elif code=='CONTROL_OUTCOME_UNKNOWN':value='CONTROL_UNCERTAIN'
                elif code=='CONTROL_CAPACITY':value='CAPACITY'
                elif code.startswith('CONTROL_JOURNAL'):
                    self.controller.host._hold('CONTROL_REOPEN_REQUIRED');value='CONTROL_UNCERTAIN'
                elif code=='STALE_CONTROLLER':value='STALE_CONTROLLER'
                else:value='REJECTED'
            raw=c.make_response(self.p,self.keeper._seed,conn.hello,request,ok,value)
            conn.output=frame(raw,c.MAX_RESPONSE);conn.sent=0;conn.incoming.clear();conn.phase='response'
            self.selector.modify(conn.socket,selectors.EVENT_WRITE,conn)
    def _write(self,conn):
        # Never disclose a queued response after a locally observed revocation.
        if self.controller.policy()!=conn.guard:
            self.counts['authority_changed']+=1;self._drop(conn);return
        n=conn.socket.send(memoryview(conn.output)[conn.sent:conn.sent+self.send_chunk])
        if n==0:self._drop(conn);return
        conn.sent+=n
        if conn.sent<len(conn.output):return
        if conn.phase=='response':self._drop(conn,completed=True);return
        conn.output=b'';conn.sent=0;conn.phase='request';self.selector.modify(conn.socket,selectors.EVENT_READ,conn)
    def diagnostics(self):
        d=super().diagnostics();d.update(profile=c.PROFILE,data_drain_member=False,max_commands_per_poll=self.max_connections,management_grant_generation=False)
        return d

    def close(self):
        if getattr(self,'closed',False):return
        if self.pid!=os.getpid() or self._thread!=threading.get_ident():raise E('CONTROL_OWNER')
        super().close()
