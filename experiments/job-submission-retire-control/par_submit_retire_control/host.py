"""Compatible four-endpoint host with explicit retirement control multiplexing."""
from contextlib import ExitStack
from par_job_control import ControlledHost
from par_job_scheduler.owner_loop import number
from par_keeper_service.transport import private_path
from par_submit_retire.store import RetiringSubmissions
from .server import Server
from .protocol import E
class RetirementControlHost:
    def __init__(self,keeper,gateway,read_path,upload_path,control_path,submit_path,jobs_root,control_root,submission_root,controller_public,controller_revision,*,submit_deadline_ms=5000,submit_max_connections=4,submission_observer=None,migrate_submissions=False,expected_submission_pin=None,**kwargs):
        paths=[private_path(p) for p in (read_path,upload_path,control_path,submit_path)]
        if len(set(paths))!=4:raise E('SOCKET_ALIAS')
        self.stack=ExitStack();self.closed=False
        try:
            self.controlled=self.stack.enter_context(ControlledHost(keeper,gateway,*paths[:3],jobs_root,control_root,controller_public,controller_revision,**kwargs))
            self.scheduler=self.controlled.scheduler;self.controller=self.controlled.controller
            self.submissions=RetiringSubmissions(self.controller,submission_root,observer=submission_observer,migrate_legacy=migrate_submissions,expected_pin=expected_submission_pin)
            self.stack.callback(self.submissions.close)
            self.submit_server=self.stack.enter_context(Server(self.submissions,paths[3],deadline_ms=submit_deadline_ms,max_connections=submit_max_connections))
        except BaseException:self.stack.close();self.closed=True;raise
    def tick(self,timeout=.01):
        self.scheduler._guard();number(timeout,0,1)
        self.submit_server.poll(timeout/4);self.controlled.tick(timeout/2);self.submit_server.poll(0)
        return self.diagnostics()
    def diagnostics(self):
        d=self.controlled.diagnostics();d['submission']=self.submit_server.diagnostics()
        d['submission_scope']='REGISTRATION_AND_EXPLICIT_PAYLOAD_RETIREMENT';return d
    def close(self):
        if self.closed:return
        self.scheduler._guard();self.stack.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
