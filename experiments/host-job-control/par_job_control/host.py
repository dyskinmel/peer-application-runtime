"""Three bounded endpoints on one owner thread; control is NOT a data reader."""
from contextlib import ExitStack
from par_job_scheduler import ScheduledHost
from par_job_scheduler.owner_loop import number
from par_keeper_service.transport import private_path
from .controller import Controller
from .server import Server
from .protocol import E
class ControlledHost:
    def __init__(self,keeper,gateway,read_path,upload_path,control_path,jobs_root,control_root,controller_public,controller_revision,*,expected_jobs_pin=None,expected_control_pin=None,control_deadline_ms=5000,control_max_connections=4,control_observer=None,**kwargs):
        paths=[private_path(p) for p in (read_path,upload_path,control_path)]
        if len(set(paths))!=3:raise E('SOCKET_ALIAS')
        self.stack=ExitStack();self.closed=False
        try:
            self.scheduler=self.stack.enter_context(ScheduledHost(keeper,gateway,*paths[:2],jobs_root,expected_jobs_pin=expected_jobs_pin,**kwargs))
            self.controller=Controller(self.scheduler,control_root,controller_public,controller_revision,expected_pin=expected_control_pin,observer=control_observer)
            self.stack.callback(self.controller.close)
            self.control=self.stack.enter_context(Server(self.controller,paths[2],deadline_ms=control_deadline_ms,max_connections=control_max_connections))
        except BaseException:self.stack.close();self.closed=True;raise
    def tick(self,timeout=.01):
        self.scheduler._guard();number(timeout,0,1)
        # Control remains live while data admission is paused. It cannot supply
        # fake zero activity: ScheduledHost still inspects both data selectors.
        self.control.poll(timeout/3)
        self.scheduler.tick(timeout/3)
        self.control.poll(0)
        return self.diagnostics()
    def diagnostics(self):
        return {'scheduler':self.scheduler.diagnostics(),'control':self.control.diagnostics(),'product_qualified':False,'synchronous_effects_preemptible':False}
    def close(self):
        if self.closed:return
        self.scheduler._guard();self.stack.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
