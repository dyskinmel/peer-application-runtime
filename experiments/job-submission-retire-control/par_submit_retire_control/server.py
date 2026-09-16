"""Two explicit request profiles share the existing fourth socket, not a fifth.

The unchanged submission hello is the authenticated transport bootstrap. New
clients require the separate retirement response profile; no silent fallback.
"""
import selectors
from par_job_submit.server import Server as RegistrationServer
from par_job_submit import protocol as legacy
from par_keeper_service.transport import frame
from .adapter import Control
from . import protocol as c
class Server(RegistrationServer):
    def __init__(self,submissions,path,**kw):
        super().__init__(submissions,path,**kw);self.retirement=Control(submissions)
    def _read(self,conn):
        data=conn.socket.recv(min(65536,conn.want-len(conn.incoming)))
        if not data:self._drop(conn);return
        conn.incoming.extend(data)
        if len(conn.incoming)==4 and conn.want==4:
            n=int.from_bytes(conn.incoming,'big')
            if not 1<=n<=legacy.MAX_REQUEST:raise c.E('FRAME_LIMIT')
            conn.want=4+n
        if len(conn.incoming)!=conn.want:return
        request=bytes(conn.incoming[4:]);conn.request=request;ok=False;value='REJECTED';proto=legacy;dispatched=False
        try:
            b,_=legacy.split(request,legacy.MAX_REQUEST)
            if type(b) is dict and b.get(1)==c.PROFILE:proto=c
            elif type(b) is not dict or b.get(1)!=legacy.PROFILE:raise c.E('RETIRE_CONTROL_PROFILE')
            public,revision=self.controller.policy()
            if public is None or (public,revision)!=conn.guard:raise c.E('STALE_CONTROLLER')
            b=proto.check_request(self.p,self.keeper.public,self.controller.host.gateway.store_id,public,revision,conn.hello,request)
            value=self.retirement.execute(b) if proto is c else self.submissions.execute(b)
            dispatched=True
            # Validate response before reporting completion. Failure here after
            # dispatch is treated as uncertain, not a request rejection.
            proto.view_shape(value);ok=True
        except Exception as exc:
            self.counts['bad_requests']+=1;code=getattr(exc,'code','')
            if self.submissions.poison or self.submissions.jobs.journal.poison:
                self.controller.host._hold('SUBMIT_REOPEN_REQUIRED');value='UNCERTAIN'
            elif dispatched and proto is c and b[3] in c.MUTATIONS:value='UNCERTAIN'
            elif code in ('SUBMIT_OUTCOME_UNKNOWN','RETIRE_CONTROL_UNCERTAIN','RETIRE_OUTCOME_UNKNOWN','RETIRE_JOURNAL_UNCERTAIN'):
                value='UNCERTAIN'
            elif code in ('SUBMIT_CAPACITY','JOB_CAPACITY','SUBMIT_TEMP_CAPACITY','RETIRE_CAPACITY'):value='CAPACITY'
            elif code in ('SUBMIT_RECONCILE_REQUIRED','SUBMIT_EXPLICIT_RETRY','SUBMIT_NOT_RECONCILABLE','SUBMIT_TARGET_CHANGED','STALE_CONTROLLER','RETIRE_RECONCILE_REQUIRED'):
                value=code
            else:value='REJECTED'
        conn.output=frame(proto.make_response(self.p,self.keeper._seed,conn.hello,request,ok,value),proto.MAX_RESPONSE)
        conn.sent=0;conn.incoming.clear();conn.phase='response';self.selector.modify(conn.socket,selectors.EVENT_WRITE,conn)
    def diagnostics(self):
        d=super().diagnostics();d.update(retirement_profile=c.PROFILE,retirement_methods=list(c.METHODS),socket_count_added=0)
        return d
