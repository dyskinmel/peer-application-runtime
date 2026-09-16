"""Cooperative safe-point scheduling over the real read and upload selectors.

No auto-run of existing jobs, no management RPC, no preemption of sync effects.
The keeper and replay gateway are borrowed; the endpoints and job journal are owned.
"""
from __future__ import annotations
import math
import os
import threading
import time
from contextlib import ExitStack
from par_management_jobs import ManagementJobs
from par_management_jobs.contract import E, fixed, CANCELLABLE
from par_verified_host import VerificationProvider
from par_verified_host.host import observe_host
from .activity import ScheduledRead,ScheduledUpload,BoundActivity

UNRESOLVED=frozenset(('OUTCOME_UNKNOWN','RETRY_READY'))
TERMINAL=frozenset(('SUCCEEDED','CANCELLED'))

def number(value,low,high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise E('SCHEDULER_INPUT')

class ScheduledHost:
    def __init__(self,keeper,gateway,read_path,upload_path,jobs_root,*,
                 drain_timeout=10.0,max_connections=8,deadline_ms=5000,send_chunk=65536,
                 expected_jobs_pin=None,job_observer=None):
        number(drain_timeout,.05,300)
        self.owner=(os.getpid(),threading.get_ident());self.closed=False;self.busy=False
        self.selected=None;self.explicit_retry=False;self.fault=None;self.deadline=None
        self.drain_timeout=drain_timeout;self.turn=0;self.effect_steps=0;self.last_step_seconds=None
        self._stack=ExitStack();self.keeper=keeper;self.gateway=gateway;self.provider=keeper.provider
        try:
            self.read=self._stack.enter_context(ScheduledRead(keeper,read_path,max_connections=max_connections,deadline_ms=deadline_ms,send_chunk=send_chunk))
            self.upload=self._stack.enter_context(ScheduledUpload(keeper,gateway,upload_path,max_connections=max_connections,deadline_ms=deadline_ms,send_chunk=send_chunk))
            self.activity=BoundActivity(keeper,self.read,self.upload)
            self.jobs=self._stack.enter_context(ManagementJobs(gateway,jobs_root,activity=self.activity.for_job,expected_pin=expected_jobs_pin,observer=job_observer))
            # No cached authorization: validate startup and all existing job facts.
            self._observe();pending=self._unresolved()
            if pending:self._pause();self.fault='RECONCILE_REQUIRED'
            self.activity.snapshot()
        except BaseException:
            self._stack.close();self.closed=True;raise
    def _guard(self):
        if self.owner!=(os.getpid(),threading.get_ident()):raise E('SCHEDULER_OWNER')
        if self.closed:raise E('CLOSED')
        if self.busy:raise E('SCHEDULER_REENTRY')
    def _observe(self):
        if self.keeper.provider is not self.provider or self.gateway.provider is not self.provider:raise E('PROVIDER_CHANGED')
        if type(self.provider) is VerificationProvider:observe_host(self.provider,self.keeper,self.gateway)
    def _unresolved(self):return [r['job_id'] for r in self.jobs.list() if r['state'] in UNRESOLVED]
    def _pause(self):
        self.read.pause_accepting();self.upload.pause_accepting()
    def _resume(self):
        try:
            self.activity.snapshot();self._observe()
            self.read.resume_accepting();self.upload.resume_accepting()
        except Exception as exc:
            self.fault=getattr(exc,'code','SCHEDULER_ERROR')
            self.read.pause_accepting();self.upload.pause_accepting();raise
    def _hold(self,code):
        self.fault=code
        self._pause()
    def submit(self,jid,**kwargs):
        self._guard();return self.jobs.submit(jid,**kwargs)
    def schedule(self,jid,*,retry=False):
        self._guard();fixed(jid)
        if type(retry) is not bool:raise E('SCHEDULER_INPUT')
        if self.selected is not None:raise E('SCHEDULER_BUSY')
        status=self.jobs.poll(jid);other=[x for x in self._unresolved() if x!=jid.hex()]
        if other:raise E('RECONCILE_REQUIRED')
        if status['state'] in TERMINAL:raise E('JOB_TERMINAL')
        if status['state']=='OUTCOME_UNKNOWN':raise E('RECONCILE_REQUIRED')
        if retry!=(status['state']=='RETRY_READY'):raise E('EXPLICIT_RETRY_REQUIRED')
        if self.fault not in (None,'RECONCILE_REQUIRED'):raise E('SCHEDULER_REOPEN_REQUIRED')
        self._observe();self.activity.snapshot();self._pause()
        self.selected=jid;self.explicit_retry=retry;self.deadline=time.monotonic()+self.drain_timeout;self.fault=None
        return self.diagnostics()
    def cancel(self,jid):
        self._guard();result=self.jobs.cancel(jid)
        if self.selected==jid:
            self.selected=None;self.deadline=None;self.explicit_retry=False;self.fault=None
        if self.selected is None and not self._unresolved():self._resume()
        return result
    def reconcile(self,jid):
        self._guard();status=self.jobs.poll(jid)
        if status['state'] not in UNRESOLVED|{'SUCCEEDED'}:raise E('NOT_RECONCILABLE')
        self._pause()
        try:
            self._observe();result=self.jobs.reconcile(jid)
        except Exception as exc:
            self._hold(getattr(exc,'code','SCHEDULER_ERROR'));raise
        if result['state']=='SUCCEEDED' and self.selected==jid:self.selected=None;self.deadline=None
        if self.selected is None and not self._unresolved():self.fault=None;self._resume()
        else:self.fault='RECONCILE_REQUIRED'
        return result
    def arm_retry(self,jid):
        self._guard()
        if self.selected not in (None,jid):raise E('SCHEDULER_BUSY')
        status=self.jobs.poll(jid)
        if status['state']!='RETRY_READY':raise E('RECONCILE_REQUIRED')
        self.selected=None;self.fault='RECONCILE_REQUIRED'
        return self.schedule(jid,retry=True)
    def tick(self,timeout=.01):
        self._guard();number(timeout,0,1);self.busy=True
        try:
            self.activity.snapshot();self._observe()
            order=(self.read,self.upload) if self.turn%2==0 else (self.upload,self.read);self.turn+=1
            for server in order:
                self._observe();server.poll(timeout/2)
            self.activity.snapshot();self._observe()
            if self.selected is not None and self.fault is None:
                status=self.jobs.poll(self.selected)
                if status['state'] in TERMINAL:self._finish()
                elif status['state'] in UNRESOLVED and not self.explicit_retry:self._hold('RECONCILE_REQUIRED')
                else:
                    activity=self.activity.snapshot()
                    if time.monotonic()>=self.deadline:self._hold('DRAIN_TIMEOUT')
                    else:
                        effect=status['state'] in ('PREPARED','RETRY_READY')
                        if effect and (activity['connections'] or activity['reader_pins']):
                            self.waiting='ACTIVE_TRANSFERS'
                        else:
                            self.waiting=None;start=time.monotonic()
                            if effect and type(self.provider) is VerificationProvider:self.provider.invalidate('management-dispatch')
                            self._observe()
                            try:
                                result=self.jobs.retry(self.selected) if self.explicit_retry else self.jobs.step(self.selected)
                            finally:
                                self.last_step_seconds=time.monotonic()-start
                                if effect:self.effect_steps+=1
                                self._observe()
                            self.explicit_retry=False
                            if result['state'] in TERMINAL:self._finish()
                            elif result['state'] in UNRESOLVED:self._hold('RECONCILE_REQUIRED')
        except Exception as exc:
            self._hold(getattr(exc,'code','SCHEDULER_ERROR'));raise
        finally:self.busy=False
        return self.diagnostics()
    def _finish(self):
        self.selected=None;self.deadline=None;self.fault=None;self.waiting=None;self._resume()
    def diagnostics(self):
        self._guard();a=self.activity.snapshot()
        mode='REVIEW_REQUIRED' if self.fault else ('DRAINING' if self.selected else 'SERVING')
        return {'mode':mode,'selected_job':self.selected.hex() if self.selected else None,
                'activity':a,'fault':self.fault,'waiting_reason':getattr(self,'waiting',None),
                'effect_steps':self.effect_steps,'last_step_seconds':self.last_step_seconds,
                'max_stages_per_tick':1,'native_storage_preemption':False,'automatic_retry':False,
                'automatic_reconcile':False,'management_socket':False,'product_qualified':False}
    def close(self):
        if self.owner!=(os.getpid(),threading.get_ident()):raise E('SCHEDULER_OWNER')
        if self.closed:return
        if self.busy:raise E('SCHEDULER_REENTRY')
        self._stack.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
