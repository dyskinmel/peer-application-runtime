"""Bounded private registration endpoint; no effect execution or dynamic dispatch."""
import os,selectors,secrets,socket,threading,time
from par_keeper_service.server import Server as BaseServer,Connection
from par_keeper_service.transport import peer_uid,frame
from . import protocol as c
E=c.E
class Server(BaseServer):
    def __init__(self,submissions,path,*,max_connections=4,deadline_ms=5000,send_chunk=65536):
        c.integer(max_connections,1,8);self.submissions=submissions;self.controller=submissions.ctl;self.pid=os.getpid()
        super().__init__(submissions.k,path,max_connections=max_connections,deadline_ms=deadline_ms,send_chunk=send_chunk)
    def _owner(self):
        if self.pid!=os.getpid():raise E('SUBMIT_OWNER')
        super()._owner();self.controller.host._guard()
    def _accept(self):
        for _ in range(self.max_connections+1):
            try:s,_=self.endpoint.socket.accept()
            except BlockingIOError:return
            if len(self.connections)>=self.max_connections:self.counts['overload']+=1;s.close();continue
            try:
                peer_uid(s);s.setblocking(False);public,rev=self.controller.policy()
                hi=c.make_hello(self.p,self.keeper._seed,store=self.controller.host.gateway.store_id,controller=public,revision=rev,boot=self._boot,challenge=secrets.token_bytes(32),deadline_ms=self.deadline_ms)
                conn=Connection(s,hi,time.monotonic()+self.deadline_ms/1000,output=frame(hi,c.MAX_HELLO));conn.guard=(public,rev)
                self.connections[s.fileno()]=conn;self.selector.register(s,selectors.EVENT_WRITE,conn);self.counts['accepted']+=1
            except E:self.connections.pop(s.fileno(),None);s.close();self.counts['bad_requests']+=1
            except BaseException:self.connections.pop(s.fileno(),None);s.close();raise
    def _read(self,conn):
        data=conn.socket.recv(min(65536,conn.want-len(conn.incoming)))
        if not data:self._drop(conn);return
        conn.incoming.extend(data)
        if len(conn.incoming)==4 and conn.want==4:
            n=int.from_bytes(conn.incoming,'big')
            if not 1<=n<=c.MAX_REQUEST:raise E('FRAME_LIMIT')
            conn.want=4+n
        if len(conn.incoming)!=conn.want:return
        request=bytes(conn.incoming[4:]);conn.request=request;ok=False;value='REJECTED'
        try:
            public,rev=self.controller.policy()
            if public is None or (public,rev)!=conn.guard:raise E('STALE_CONTROLLER')
            b=c.check_request(self.p,self.keeper.public,self.controller.host.gateway.store_id,public,rev,conn.hello,request)
            value=self.submissions.execute(b);ok=True
        except Exception as exc:
            self.counts['bad_requests']+=1;code=getattr(exc,'code','')
            if self.submissions.poison or self.submissions.jobs.journal.poison:
                self.controller.host._hold('SUBMIT_REOPEN_REQUIRED');value='UNCERTAIN'
            elif code=='SUBMIT_OUTCOME_UNKNOWN':value='UNCERTAIN'
            elif code in ('SUBMIT_CAPACITY','JOB_CAPACITY','SUBMIT_TEMP_CAPACITY'):value='CAPACITY'
            elif code in ('SUBMIT_RECONCILE_REQUIRED','SUBMIT_EXPLICIT_RETRY','SUBMIT_NOT_RECONCILABLE','SUBMIT_TARGET_CHANGED','STALE_CONTROLLER'):value=code
            else:value='REJECTED'
        conn.output=frame(c.make_response(self.p,self.keeper._seed,conn.hello,request,ok,value),c.MAX_RESPONSE)
        conn.sent=0;conn.incoming.clear();conn.phase='response';self.selector.modify(conn.socket,selectors.EVENT_WRITE,conn)
    def _write(self,conn):
        if self.controller.policy()!=conn.guard:self.counts['authority_changed']+=1;self._drop(conn);return
        n=conn.socket.send(memoryview(conn.output)[conn.sent:conn.sent+self.send_chunk])
        if n==0:self._drop(conn);return
        conn.sent+=n
        if conn.sent<len(conn.output):return
        if conn.phase=='response':self._drop(conn,completed=True);return
        conn.output=b'';conn.sent=0;conn.phase='request';self.selector.modify(conn.socket,selectors.EVENT_READ,conn)
    def diagnostics(self):
        d=super().diagnostics();d.update(profile=c.PROFILE,data_drain_member=False,automatic_job_selection=False,management_grant_generation=False);return d
    def close(self):
        if getattr(self,'closed',False):return
        if self.pid!=os.getpid() or self._thread!=threading.get_ident():raise E('SUBMIT_OWNER')
        super().close()
