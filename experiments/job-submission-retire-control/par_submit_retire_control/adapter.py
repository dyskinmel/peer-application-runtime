"""Narrow owner adapter. Registration and job execution are never dispatched here."""
from par_job_submit import protocol as s
from . import protocol as c
class Control:
    def __init__(self,submissions):self.st=submissions;self.ctl=submissions.ctl
    def _view(self,descriptor,kind='status'):
        self.st.audit();d=s.check_descriptor(self.st.p,descriptor);m,_=self.st._read(d[5])
        if m[4]!=descriptor or (d[2],d[3])!=(self.st.k.public,self.st.host.gateway.store_id):raise c.E('RETIRE_CONTROL_TARGET')
        public,revision=self.ctl.policy()
        if public is None:raise c.E('STALE_CONTROLLER')
        v={'kind':kind,'job_id':d[5].hex(),'descriptor_hash':s.sha(descriptor).hex(),
           'stage_state':m[7],'controller_revision':revision,'product_qualified':False}
        if kind=='proposal':v['proposal']=self.st.proposal(descriptor)
        else:v['retirement']=self.st.retirement_status(d[5]) if self.st.retirement_path(d[5]).exists() else None
        c.view_shape(v);return v
    def execute(self,body):
        self.st.guard();c.request_shape(self.st.p,body)
        action,descriptor,authorization=body[3],body[4],body[5]
        # Verify the exact retained descriptor before touching a mutation.
        self._view(descriptor)
        if action=='proposal':return self._view(descriptor,'proposal')
        if action=='status':return self._view(descriptor)
        # Connection proof never substitutes for either of these approvals.
        from par_submit_retire import contract as r
        a=r.check_request(self.st.p,authorization)
        if self.ctl.policy()!=(a[8],a[9]):raise c.E('STALE_CONTROLLER')
        try:
            if action=='retire':self.st.retire(authorization)
            elif action=='rebind':self.st.rebind(authorization)
            elif action=='reconcile_registration':self.st.reconcile_registration(authorization)
            else:raise c.E('RETIRE_CONTROL_METHOD')
        except Exception as exc:
            # Unexpected failure after dispatch cannot imply "not executed".
            if not isinstance(exc,c.E):raise c.E('RETIRE_CONTROL_UNCERTAIN') from None
            raise

        try:return self._view(descriptor)
        except Exception:raise c.E('RETIRE_CONTROL_UNCERTAIN') from None
