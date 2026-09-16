"""Prepare, one dispatch, original-ID inquiry and explicit retire.

No public/owner-wire apply operation is added. A cooperating trusted owner uses
one journal per stable document/store/inbox/device binding. It must persist the
journal pin outside this directory. Historical receipt != current availability.
"""
from __future__ import annotations
import asyncio,hashlib,math,time
from product.wp04.application import DocumentApplier
from product.wp04 import exchange as x
from product.runtime_read.fetch import FetchApplicationController
from product.wp09.par_secure_fetch.persistence import require,FetchError
from product.wp09.par_secure_fetch.client import error_code
from .model import ApplicationIntent,check_binding,check_receipt,MAX_BYTES
from .journal import IntentJournal

class DurableApplication:
    @staticmethod
    def binding(controller):
        require(type(controller)is FetchApplicationController,'APPLICATION_BINDING')
        app=controller._application
        require(type(app)is DocumentApplier and not app._allow and app._inbox is controller._source.box,'APPLICATION_BINDING')
        return check_binding(x.pack([list(controller._plan.scope[:5]),app.owner._storage.generation,
                    controller._plan.inbox_generation,hashlib.sha256(app._cert).digest()],MAX_BYTES))

    def __init__(self,journal,controller):
        require(type(journal)is IntentJournal,'JOURNAL_REQUIRED')
        require(journal._binding==self.binding(controller),'JOURNAL_BINDING')
        self.journal=journal;self.controller=controller;self._app=controller._application;self._busy=False
        journal.audit()

    def _enter(self):
        require(not self._busy,'INTENT_BUSY')
        require(self.journal._binding==self.binding(self.controller),'JOURNAL_BINDING')
        self.journal.audit()

    def _authority(self):
        self.controller._guard()
        return self._app._auth()[0]

    def _current(self,digest):
        intent=self.journal.current
        require(intent is not None and type(digest)is str and intent.digest==digest,'INTENT_PIN')
        require(intent.targets==self.controller._targets,'APPLICATION_TARGETS')
        return intent

    def _result(self,state=None,reason=None):
        value=self.journal.status();value['operationState']=state or value['state'];value['reason']=reason
        value['needsInquiry']=value['state']in('DISPATCHED','OBSERVED')
        # These top-level booleans describe THIS journal action, not the supplied
        # application's materializer. The nested row identifies historical evidence.
        return value

    def prepare(self,operation_id,*,expected_revision,expected_observation):
        self._enter();c=self.controller;c._intent(operation_id,expected_revision)
        c._command(expected_observation);self._busy=True
        try:
            app=self._app;row=self._authority();app._audit()
            i=ApplicationIntent(c._plan.scope,app.owner._storage.generation,c._plan.inbox_generation,
                    hashlib.sha256(app._cert).digest(),operation_id,expected_revision,c._targets,
                    row['row_digest'],app._pool_digest(app._external()),c._plan.binding.generation)
            active=self.journal.current
            if active is not None and self.journal.status()['state']not in('RETIRED','ABANDONED'):
                # The journal, not a newly captured view, controls active-ID admission.
                self.journal.prepare(i);return self._result()
            require(app.inquire(operation_id,c._targets,expected_revision=expected_revision)is None,'OPERATION_ALREADY_COMMITTED')
            frontier=app._frontier();require((frontier['revision']if frontier else 0)==expected_revision,'STALE_FRONTIER')
            require(self._authority()['row_digest']==i.authority_digest,'OWNER_STATE_CHANGED')
            self.journal.prepare(i);return self._result()
        finally:self._busy=False

    @staticmethod
    def _cancel(cancel,deadline):
        require(cancel is None or isinstance(cancel,asyncio.Event),'INVALID_CANCEL')
        try:task=asyncio.current_task()
        except RuntimeError:task=None
        if task is not None and task.cancelling():raise asyncio.CancelledError
        require(cancel is None or not cancel.is_set(),'CANCELLED')
        require(time.monotonic()<deadline,'INTENT_DEADLINE')

    def execute(self,digest,*,expected_observation,timeout=30.0,cancel=None):
        self._enter();i=self._current(digest)
        require(self.journal.status()['state']=='PREPARED','INQUIRY_REQUIRED')
        require(type(timeout)in(int,float)and math.isfinite(timeout)and .05<=timeout<=120,'INVALID_TIMEOUT')
        require(cancel is None or isinstance(cancel,asyncio.Event),'INVALID_CANCEL')
        deadline=time.monotonic()+timeout
        c=self.controller;c._command(expected_observation)
        require(c._plan.binding.generation==i.connection_generation,'STALE_GENERATION')
        require(self._authority()['row_digest']==i.authority_digest,'OWNER_STATE_CHANGED')
        require(self._app._pool_digest(self._app._external())==i.input_digest,'INPUTS_CHANGED')
        self._busy=True;dispatched=False
        try:
            self._cancel(cancel,deadline)
            self._app._engine() # Never make a synthetic/default engine real.
            self.journal.dispatch(digest);dispatched=True
            self._cancel(cancel,deadline)
            require(self._authority()['row_digest']==i.authority_digest,'OWNER_STATE_CHANGED')
            require(self._app._pool_digest(self._app._external())==i.input_digest,'INPUTS_CHANGED')
            row=self._app.apply(i.operation_id,i.targets,expected_revision=i.expected_revision)
            self._cancel(cancel,deadline);self._authority();check_receipt(i,row)
            self.journal.observe(digest,row)
            self._cancel(cancel,deadline);self._authority()
            return self._result('OBSERVED_APPLICATION_RECORD')
        except BaseException as exc:
            # A failed journal append poisons the handle. It cannot manufacture a
            # fresh status; callers must reopen pinned bytes and inquire.
            if not isinstance(exc,Exception):raise
            if self.journal._poisoned:raise
            code=error_code(exc)
            state='OUTCOME_UNKNOWN'if dispatched else ('CORE_BLOCKED'if code in
                ('CORE_UNAVAILABLE','CORE_NOT_REAL','CORE_RUNTIME_CHANGED','CORE_IDENTITY_CHANGED','CORE_TIMEOUT')else
                'CANCELLED'if code=='CANCELLED'else'REJECTED')
            return self._result(state,code)
        finally:self._busy=False

    def inquire(self,digest):
        self._enter();i=self._current(digest);self._busy=True
        try:
            self._authority()
            row=self._app.inquire(i.operation_id,i.targets,expected_revision=i.expected_revision)
            self._authority()
            if row is None:
                require(self.journal.status()['receipt']is None,'RECEIPT_CONFLICT')
                return self._result('NOT_OBSERVED')
            check_receipt(i,row)
            require(self.journal.status()['state']in('DISPATCHED','OBSERVED','RETIRED'),'UNEXPECTED_APPLICATION_RECORD')
            if self.journal.status()['state']!='RETIRED':self.journal.observe(digest,row)
            else:
                from product.wp04.contracts import canonical
                require(canonical(row)==canonical(self.journal.status()['receipt']),'RECEIPT_CONFLICT')
            self._authority()
            return self._result('OBSERVED_APPLICATION_RECORD')
        except Exception as exc:
            if self.journal._poisoned:raise
            return self._result('INQUIRY_FAILED',error_code(exc))
        finally:self._busy=False

    def retire(self,digest):
        self._enter();self._current(digest)
        require(self.journal.status()['state']=='OBSERVED','RECEIPT_REQUIRED')
        value=self.inquire(digest)
        require(value['operationState']=='OBSERVED_APPLICATION_RECORD','RECEIPT_REQUIRED')
        self._authority();self.journal.retire(digest);return self._result()

    def abandon(self,digest):
        self._enter();self._current(digest);self._authority()
        self.journal.abandon(digest);return self._result()

class AnchoredApplication(DurableApplication):
    """Mutation capability requiring an owner-supplied durable checkpoint port.

    This is a Python owner boundary, not a public RPC and not a claim that a local
    filesystem adapter provides an OS key vault or whole-volume rollback safety.
    Existing unanchored DurableApplication remains available for the 0050 API.
    """
    def __init__(self,journal,controller):
        require(type(journal)is IntentJournal and journal.anchored,'PIN_STORE_REQUIRED')
        super().__init__(journal,controller)

    def _enter(self):
        require(self.journal.anchored,'PIN_STORE_REQUIRED')
        super()._enter()
