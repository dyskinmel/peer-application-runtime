"""Control a pre-registered job, without minting job authorization or auto-retry."""
from . import protocol as c
from .journal import Journal
E=c.E
class Controller:
    def __init__(self,host,root,public,revision,**kwargs):
        host._guard();self.host=host;self.p=host.provider;self.busy=False
        self.journal=Journal(host,root,public,revision,**kwargs)
    def policy(self):
        self.host._guard();b=self.journal.policy();return b[5][-1][1],b[5][-1][0]
    def replace_controller(self,public,revision):
        self.host._guard()
        if self.busy:raise E('CONTROL_REENTRY')
        self.journal.rotate(public,revision)
    def _view(self,i,outcome,duplicate=False):
        d=self.host.diagnostics();a=d['activity']
        h={k:d[k] for k in ('mode','selected_job','fault','effect_steps','native_storage_preemption')}
        h.update({k:a[k] for k in ('connections','reader_pins','read_accepting','upload_accepting')})
        v={'operation_id':i.operation_id.hex(),'action':i.action,'job_id':i.job_id.hex() if i.job_id else None,
           'outcome':outcome,'error':None,'duplicate':duplicate,'job':self.host.jobs.poll(i.job_id) if i.job_id else None,'host':h,
           'jobs_pin':c.dump(self.host.jobs.pin(),32768).hex(),'control_pin':c.dump(self.journal.pin(),20000).hex(),
           'policy_revision':i.revision,'product_qualified':False}
        c.view_shape(v);return v
    def execute(self,raw):
        self.host._guard()
        if self.busy:raise E('CONTROL_REENTRY')
        public,revision=self.policy()
        if public is None:raise E('STALE_CONTROLLER')
        i=c.check_intent(self.p,self.host.keeper.public,self.host.gateway.store_id,public,revision,raw)
        self.journal.audit()
        if i.action=='status':return self._view(i,'STATUS')
        previous=self.journal.lookup(i)
        if previous:return self._view(i,previous,True)
        # Read-only preflight: no new job, no arbitrary method, no activity change.
        state=self.host.jobs.poll(i.job_id)['state']
        allowed={'select':('QUEUED','VALIDATED','PREPARED'),'cancel':('QUEUED','VALIDATED','PREPARED','CANCELLED'),
                 'reconcile':('OUTCOME_UNKNOWN','RETRY_READY','SUCCEEDED'),'retry':('RETRY_READY',)}
        if state not in allowed[i.action]:raise E('CONTROL_JOB_STATE')
        self.busy=True;started=False
        try:
            self.journal.start(i);started=True
            self.journal.emit('before_dispatch')
            # Callbacks/fault injectors may change the owner policy. Recheck it.
            if self.policy()!=(i.controller,i.revision):raise E('STALE_CONTROLLER')
            outcome='ACCEPTED'
            try:
                if i.action=='select':self.host.schedule(i.job_id)
                elif i.action=='cancel':self.host.cancel(i.job_id)
                elif i.action=='reconcile':self.host.reconcile(i.job_id)
                elif i.action=='retry':self.host.arm_retry(i.job_id)
                else:raise E('CONTROL_METHOD')
                self.journal.emit('after_dispatch')
            except Exception:
                # An exception is not proof that scheduler/job state did not change.
                outcome='OUTCOME_UNKNOWN'
            self.journal.finish(i,outcome)
            if self.policy()!=(i.controller,i.revision):raise E('STALE_CONTROLLER')
            return self._view(i,outcome)
        except Exception:
            if started:raise E('CONTROL_OUTCOME_UNKNOWN') from None
            raise
        finally:self.busy=False
    def close(self):self.journal.close()
