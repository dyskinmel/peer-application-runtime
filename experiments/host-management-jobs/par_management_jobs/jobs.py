"""Cooperative owner API. step() performs one stage, never a background task.

The existing mutation is synchronous within one step. The durable EXECUTING marker
is the conservative no-cancellation boundary; it may precede any actual effect.
Interrupted execution must be explicitly reconciled before an explicit retry.
"""
from contextlib import contextmanager
from . import contract as c
from .backend import WindowBackend
from .journal import Journal
E=c.E

class ManagementJobs:
    def __init__(self,gateway,root,*,activity=None,max_jobs=c.MAX_JOBS,max_bytes=c.MAX_TOTAL,observer=None,expected_pin=None):
        if activity is not None and not callable(activity):raise E('JOB_ACTIVITY')
        self.activity=activity;self.backend=WindowBackend(gateway)
        self.journal=Journal(self.backend,root,max_jobs=max_jobs,max_bytes=max_bytes,observer=observer)
        if expected_pin is not None:
            try:self.verify_pin(expected_pin)
            except BaseException:self.close();raise
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):self.journal.close()
    @contextmanager
    def _operation(self):
        self.journal.audit();self.journal.busy=True
        try:yield
        finally:self.journal.busy=False
    def _read(self,jid):return self.journal.read(jid)[:2]
    def _idle(self):
        if self.activity is None:raise E('ACTIVITY_OBSERVER_REQUIRED')
        n=self.activity()
        if type(n) is not int or not 0<=n<=65536:raise E('JOB_ACTIVITY')
        return n==0 and not self.backend.active()
    def _status(self,b,a,waiting=None):
        event=b[13][-1];state=event[1];verified=False
        if state=='SUCCEEDED':
            evidence=self.backend.probe(b,a)
            if (evidence.state,evidence.result,evidence.witness)!=('APPLIED',event[2],event[3]):raise E('JOB_RESULT_MISMATCH')
            verified=True
        display='OUTCOME_UNKNOWN' if state=='EXECUTING' else state
        return {'job_id':b[4].hex(),'action':b[5],'state':display,'journal_state':state,
                'revision':event[0],'input_digest':c.intent(b).hex(),'target_sequence':b[10][1],
                'cancellable':state in c.CANCELLABLE,'may_have_effect':any(e[1]=='EXECUTING' for e in b[13]),
                'requires_reconciliation':state in ('EXECUTING','OUTCOME_UNKNOWN'),
                'explicit_retry_required':state=='RETRY_READY','result_verified':verified,
                'result_digest':c.sha(event[2]).hex() if verified else None,
                'waiting_reason':waiting,'progress_total':None,'product_qualified':False}
    def submit(self,jid,*,action,command=None,archive=None):
        c.arguments(jid,action,command,archive)
        with self._operation():
            path=self.journal.path(jid)
            if path.exists():
                b,a=self._read(jid)
                if not c.input_equal(b,action,command,archive):raise E('JOB_CONFLICT')
                return self._status(b,a)
            # audit is an entry method and checks busy; direct finite read here.
            rows=[self.journal.read(bytes.fromhex(p.stem)) for p in sorted(self.journal.root.glob('*.job'))]
            needed=(len(command or b'')+len(archive or b'')+262144)
            if len(rows)>=self.journal.config[4] or sum(len(r[2])+262144 for r in rows)+needed>self.journal.config[5]:raise E('JOB_CAPACITY')
            authority,pin,phase,window=self.backend.context()
            b={0:1,1:c.PROFILE,2:self.backend.k.public,3:self.backend.g.store_id,4:jid,5:action,
               6:command,7:c.sha(archive) if archive else None,8:len(archive) if archive else 0,
               9:authority,10:pin,11:phase,12:window,13:[{0:0,1:'QUEUED',2:None,3:None}]}
            if any(c.intent(r[0])==c.intent(b) for r in rows):raise E('JOB_ALIAS')
            self.backend.validate(b,archive or b'')
            self.journal.persist(b,archive or b'','queued')
            return self._status(b,archive or b'')
    def poll(self,jid):
        with self._operation():b,a=self._read(jid);return self._status(b,a)
    def list(self):
        with self._operation():
            return [self._status(*self._read(bytes.fromhex(p.stem))) for p in sorted(self.journal.root.glob('*.job'))]
    def cancel(self,jid):
        with self._operation():
            b,a=self._read(jid);state=b[13][-1][1]
            if state=='CANCELLED':return self._status(b,a)
            if state not in c.CANCELLABLE:raise E('CANCEL_TOO_LATE')
            b=self.journal.transition(b,a,'CANCELLED');return self._status(b,a)
    def step(self,jid):
        with self._operation():
            b,a=self._read(jid);state=b[13][-1][1]
            if state=='SUCCEEDED':return self._status(b,a)
            if state=='CANCELLED':raise E('JOB_CANCELLED')
            if state in ('EXECUTING','OUTCOME_UNKNOWN'):raise E('RECONCILE_REQUIRED')
            if state=='RETRY_READY':raise E('EXPLICIT_RETRY_REQUIRED')
            self.backend.validate(b,a)
            if state=='QUEUED':b=self.journal.transition(b,a,'VALIDATED')
            elif state=='VALIDATED':b=self.journal.transition(b,a,'PREPARED')
            elif state=='PREPARED':return self._execute(b,a)
            return self._status(b,a)
    def _execute(self,b,a):
        if len(b[13])>c.MAX_EVENTS-3:raise E('JOB_HISTORY_LIMIT')
        if not self._idle():return self._status(b,a,'ACTIVE_TRANSFERS')
        # A trusted activity callback may yield/reenter the host; recheck afterward.
        self.backend.validate(b,a)
        b=self.journal.transition(b,a,'EXECUTING')
        try:
            self.journal.emit('effect.before_dispatch')
            if not self._idle():raise E('JOB_ACTIVITY_CHANGED')
            self.backend.validate(b,a)
            self.backend.apply(b,a)
            self.journal.emit('effect.after_dispatch')
            fact=self.backend.probe(b,a)
            if fact.state!='APPLIED':raise E('JOB_EFFECT_UNCONFIRMED')
            b=self.journal.transition(b,a,'SUCCEEDED',fact.result,fact.witness)
        except Exception:
            # If the journal failed its durable boundary, don't create a second
            # competing history. Reopen is required; EXECUTING remains uncertain.
            if self.journal.poison:raise E('JOB_JOURNAL_UNCERTAIN') from None
            b=self.journal.transition(b,a,'OUTCOME_UNKNOWN')
        return self._status(b,a)
    def reconcile(self,jid):
        with self._operation():
            b,a=self._read(jid);state=b[13][-1][1]
            if state=='SUCCEEDED':return self._status(b,a)
            if state not in ('EXECUTING','OUTCOME_UNKNOWN','RETRY_READY'):raise E('NOT_RECONCILABLE')
            fact=self.backend.probe(b,a)
            if fact.state=='APPLIED':b=self.journal.transition(b,a,'SUCCEEDED',fact.result,fact.witness)
            elif state!='RETRY_READY':
                if len(b[13])>c.MAX_EVENTS-2:raise E('JOB_HISTORY_LIMIT')
                self.backend.validate(b,a)
                b=self.journal.transition(b,a,'RETRY_READY')
            return self._status(b,a)
    def retry(self,jid):
        with self._operation():
            b,a=self._read(jid)
            if b[13][-1][1]!='RETRY_READY':raise E('RECONCILE_REQUIRED')
            fact=self.backend.probe(b,a)
            if fact.state=='APPLIED':
                b=self.journal.transition(b,a,'SUCCEEDED',fact.result,fact.witness);return self._status(b,a)
            self.backend.validate(b,a);return self._execute(b,a)
    def result(self,jid):
        with self._operation():
            b,a=self._read(jid)
            if not self._status(b,a)['result_verified']:raise E('RESULT_NOT_VERIFIED')
            return bytes(b[13][-1][2])

    def pin(self):
        """Caller must preserve this outside the journal rollback domain."""
        with self._operation():
            items=[]
            for path in sorted(self.journal.root.glob('*.job')):
                b,a=self._read(bytes.fromhex(path.stem))
                items.append([b[4],len(b[13])-1,c.sha(c.dump(b))])
            return {0:c.PROFILE,1:self.backend.k.public,2:self.backend.g.store_id,3:items}
    def verify_pin(self,pin):
        with self._operation():
            try:
                c.keys(pin,range(4))
                if (pin[0],pin[1],pin[2])!=(c.PROFILE,self.backend.k.public,self.backend.g.store_id):raise ValueError()
                if type(pin[3]) is not list or len(pin[3])>c.MAX_JOBS:raise ValueError()
                ids=[]
                for item in pin[3]:
                    if type(item) is not list or len(item)!=3:raise ValueError()
                    jid,rev,expected=item;c.fixed(jid);c.fixed(expected);c.integer(rev,0,c.MAX_EVENTS-1);ids.append(jid)
                    b,a=self._read(jid)
                    if rev>=len(b[13]):raise ValueError()
                    b=c.load(c.dump(b));b[13]=b[13][:rev+1]
                    if c.sha(c.dump(b))!=expected:raise ValueError()
                if ids!=sorted(set(ids)):raise ValueError()
            except Exception:raise E('JOB_PIN') from None
            return True
