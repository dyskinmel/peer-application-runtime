"""Owned fetch-candidate observation and explicit validation/application bridge.

The panel is not a shared-commit receipt. Application writes are exclusively the
existing DocumentApplier's responsibility. No fetch, apply or replay on observe.
"""
from __future__ import annotations
import copy
import hashlib
import secrets
from product.wp04 import exchange as x
from product.wp04.contracts import canonical
from product.wp04.application import DocumentApplier
from product.wp09.par_secure_fetch import FetchPlan
from product.wp09.par_secure_fetch.client import error_code
from product.wp09.par_secure_fetch.persistence import FetchError, require
from product.wp09.par_secure_fetch.dependencies import targets_owned, source_guard

PROFILE = 'par-fetch-observation-local-0046'
MAX_OBSERVATION_BYTES = 262144
STATES = ('NOT_OBSERVED', 'WAITING_DEPENDENCIES', 'READY_FOR_CORE', 'QUARANTINED',
          'WAITING_AUTHORITY', 'REBASE_REQUIRED', 'INVALID_DEPENDENCY_GRAPH', 'RESOURCE_BLOCKED')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

class FetchApplicationController:
    def __init__(self, plan, source, targets, current_generation, *, core=None, application=None):
        require(type(plan) is FetchPlan and type(source) is x.Source and callable(current_generation), 'CONTROLLER_INPUT')
        self._plan, self._source, self._generation = plan, source, current_generation
        self._targets = targets_owned(targets)
        self._closed = False
        self._busy = False
        self._sequence = 0
        self._stream = secrets.token_hex(16)
        self._core = core
        self._application = application
        self._validation = {}
        self._validation_revision = None
        self._last = None
        self._unresolved_intent = None
        self._operation = {'id': None, 'state': 'NOT_REQUESTED', 'reason': None,
                           'revision': None, 'expectedRevision': None}
        self._guard()
        if application is not None:
            require(type(application) is DocumentApplier and application.owner is source.owner
                    and application._inbox is source.box and not application._allow,
                    'APPLICATION_BINDING')
            require(canonical(application._scope) == canonical(source.box._scope_data)
                    and application._cert == source.certificate, 'APPLICATION_BINDING')
            if core is not None:
                require(application._core is core, 'APPLICATION_BINDING')
            self._core = application._core

    def _guard(self):
        require(not self._closed, 'CONTROLLER_CLOSED')
        return source_guard(self._source, self._plan.binding, self._plan.inbox_generation, self._generation)

    def _enter(self):
        require(not self._busy, 'CONTROLLER_BUSY')
        return self._guard()

    def pin(self):
        self._guard()
        s = self._plan.scope
        return {'profile': PROFILE, 'scope': {'appId': s[0], 'spaceId': s[1].hex(),
                    'documentId': s[2].hex(), 'epoch': str(s[3]), 'schemaId': s[4].hex(),
                    'controlHead': s[5].hex()},
                'planDigest': self._plan.digest,
                'targetDigest': digest([v.hex() for v in self._targets]),
                'inboxGeneration': self._plan.inbox_generation,
                'storeGeneration': self._source.owner._storage.generation.hex(),
                'connectionGeneration': str(self._plan.binding.generation), 'streamId': self._stream}

    @property
    def operation(self):
        """Original ID remains inspectable even if the owner's authority changed."""
        return copy.deepcopy(self._operation)

    def close(self):
        require(not self._busy, 'CONTROLLER_BUSY')
        self._closed = True
        self._last = None
        self._validation.clear()

    def observe(self):
        before = self._enter()
        self._busy = True
        try:
            if before != self._validation_revision:
                self._validation.clear()
            rows = []
            for eid in self._targets:
                view = self._source.box.inspect(eid)
                require(view['state'] in STATES, 'OBSERVATION_SCHEMA')
                rows.append({'envelopeId': eid.hex(), 'state': view['state'],
                             'inboxStored': view['inboxStored'],
                             'missingInner': view['missing'], 'missingPrevious': view['missingPrevious'],
                             'validation': copy.deepcopy(self._validation.get(eid))})
            pin = self.pin()
            require(before == self._guard(), 'LOCAL_VIEW_CHANGED')
            require(self._sequence < 2**64 - 1, 'SEQUENCE_EXHAUSTED')
            self._sequence += 1
            value = {'profile': PROFILE, 'pin': pin, 'sequence': str(self._sequence),
                     'localRevision': before.hex(), 'records': rows,
                     'operation': self.operation,
                     'innerValidated': False, 'applied': False, 'localCommitted': False,
                     'replicated': False, 'acknowledged': False, 'productQualified': False}
            value['revision'] = digest(value)
            require(len(canonical(value)) <= MAX_OBSERVATION_BYTES, 'OBSERVATION_BUDGET')
            self._last = copy.deepcopy(value)
            return value
        finally:
            self._busy = False

    def _command(self, expected):
        current = self._enter()
        require(type(expected) is str and self._last is not None
                and expected == self._last['revision'], 'STALE_OBSERVATION')
        require(current.hex() == self._last['localRevision'], 'LOCAL_VIEW_CHANGED')
        self._last = None  # A fresh explicit observation is required after each command.
        return current

    def validate(self, *, expected_revision):
        before = self._command(expected_revision)
        self._busy = True
        checked = {}
        self._validation.clear()
        self._validation_revision = None
        try:
            for eid in self._targets:
                self._guard()
                result = self._source.box.validate(eid, self._core, allow_contract_double=False)
                checked[eid] = {'state': result['state'], 'reason': result.get('reason')}
            require(before == self._guard(), 'LOCAL_VIEW_CHANGED')
            self._validation, self._validation_revision = checked, before
        finally:
            self._busy = False
        return self.observe()

    @staticmethod
    def _intent(operation_id, expected_revision):
        require(type(operation_id) is bytes and len(operation_id) == 16, 'INVALID_OPERATION_ID')
        require(type(expected_revision) is int and 0 <= expected_revision < 64, 'INVALID_REVISION')

    def apply(self, operation_id, *, expected_revision, expected_observation):
        self._intent(operation_id, expected_revision)
        require(self._unresolved_intent is None, 'INQUIRY_REQUIRED')
        if self._operation['id'] == operation_id.hex():
            require(self._operation['expectedRevision'] == expected_revision, 'OPERATION_ID_CONFLICT')
        self._command(expected_observation)
        self._operation = {'id': operation_id.hex(), 'state': 'REQUESTED', 'reason': None,
                           'revision': None, 'expectedRevision': expected_revision}
        self._busy = True
        attempted = False
        try:
            app = self._application
            require(app is not None, 'CORE_UNAVAILABLE')
            app._engine()  # Refuse unavailable/synthetic engines before any nonce or write.
            self._guard()
            attempted = True
            receipt = app.apply(operation_id, self._targets, expected_revision=expected_revision)
            self._guard()
            self._operation.update(state='OBSERVED_APPLICATION_RECORD', revision=receipt['revision'])
        except BaseException as exc:
            code = error_code(exc)
            if attempted:
                # Even an exception reporting a core failure can follow an
                # application commit. Only inquiry of this exact intent resolves it.
                state = 'OUTCOME_UNKNOWN'
                self._unresolved_intent = (operation_id, expected_revision)
            elif code in ('CORE_UNAVAILABLE', 'CORE_NOT_REAL', 'CORE_RUNTIME_CHANGED',
                          'CORE_IDENTITY_CHANGED', 'CORE_TIMEOUT'):
                state = 'CORE_BLOCKED'
            else:
                state = 'REJECTED'
            self._operation.update(state=state, reason=code)
            if not isinstance(exc, Exception):
                raise
        finally:
            self._busy = False
        return self.observe()

    def inquire(self, operation_id, *, expected_revision, expected_observation):
        self._intent(operation_id, expected_revision)
        require(self._unresolved_intent is None
                or self._unresolved_intent == (operation_id, expected_revision),
                'ORIGINAL_OPERATION_REQUIRED')
        self._command(expected_observation)
        self._busy = True
        self._operation = {'id': operation_id.hex(), 'state': 'INQUIRY_FAILED', 'reason': None,
                           'revision': None, 'expectedRevision': expected_revision}
        try:
            require(self._application is not None, 'APPLICATION_UNAVAILABLE')
            row = self._application.inquire(operation_id, self._targets, expected_revision=expected_revision)
            self._guard()
            self._operation.update(state='NOT_OBSERVED' if row is None else 'OBSERVED_APPLICATION_RECORD',
                                   revision=None if row is None else row['revision'])
            if row is not None:
                self._unresolved_intent = None
        except Exception as exc:
            self._operation['reason'] = error_code(exc)
        finally:
            self._busy = False
        return self.observe()
