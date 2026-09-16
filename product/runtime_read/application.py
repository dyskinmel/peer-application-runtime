"""Read-only schema4 observations from a trusted, already-owned application.

Candidate materializations are authenticated locally but never exposed as note
text. A core-labelled record alone is not semantic proof: release of a note
requires an owner-pinned core, re-execution over exact signed inputs, and equality
with the encrypted materialization. This is NOT an authenticated transport, a
sandbox, a global-freshness oracle, or a shared-write API.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from par_wire.codec import decode
from product.wp04.application import (
    DocumentApplier, MAX_INPUTS, MAX_NOTE_BYTES, check_materialization,
)
from product.wp04 import application_schema as schema
from product.wp04.contracts import canonical, hex32, SharedChangeError
from .observer import ObservationError

PROFILE = 'par-application-observation-local-0036'
UNAVAILABLE_CORE = {'CORE_UNAVAILABLE', 'CORE_TIMEOUT', 'CORE_NOT_REAL'}


def require(condition: bool, code: str = 'APPLICATION_READ_FAILED') -> None:
    if not condition:
        raise ObservationError(code)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class ApplicationObserver:
    """One owner/process/thread; no writes, migration, signing or automatic retry.

    ``expected_engine`` must come from trusted owner configuration, never from
    an input event's self-reported engine field. Ports are trusted executable
    code; an arbitrary in-process caller can fake them, as it can fake the DB.
    """

    def __init__(self, application: DocumentApplier, *, expected_engine=None):
        require(isinstance(application, DocumentApplier), 'INVALID_INPUT')
        if expected_engine is not None:
            require(type(expected_engine) is dict and set(expected_engine) ==
                    {'name', 'version', 'kind', 'digest'}, 'ENGINE_PIN_INVALID')
            require(expected_engine['name'] == '@automerge/automerge' and
                    expected_engine['version'] == '3.4.1' and
                    expected_engine['kind'] == 'automerge' and
                    hex32(expected_engine['digest']), 'ENGINE_PIN_INVALID')
        self._application = application
        self._engine = json.loads(canonical(expected_engine)) if expected_engine is not None else None
        self._identity = (os.getpid(), threading.get_ident())
        self._closed = False
        self._busy = False
        self._stream = secrets.token_hex(16)
        self._sequence = 0
        self._fixed_pin = self._pin_value()
        self._seen_frontier = None

    def _enter(self):
        require(self._identity == (os.getpid(), threading.get_ident()), 'WRONG_OWNER')
        require(not self._closed, 'OBSERVER_CLOSED')
        require(not self._busy, 'REENTRANT_OPERATION')
        self._application._enter()

    def close(self):
        require(self._identity == (os.getpid(), threading.get_ident()), 'WRONG_OWNER')
        require(not self._busy, 'REENTRANT_OPERATION')
        # Does not close an application owned by somebody else. No secure-erasure claim.
        self._closed = True

    def pin(self):
        self._enter()
        current = self._pin_value()
        require(current == self._fixed_pin, 'SCOPE_MISMATCH')
        return current

    def _pin_value(self):
        a = self._application
        return {
            'scope': dict(appId=a._scope['app'], spaceId=a._scope['space'],
                          documentId=a._scope['document'], epoch=str(a._epoch),
                          schemaId=a._scope['schema']),
            'storeGeneration': a.owner._storage.generation.hex(),
            'certificateDigest': hashlib.sha256(a._cert).hexdigest(),
            'streamId': self._stream,
            'engineDigest': self._engine['digest'] if self._engine is not None else None,
        }

    def _stamp(self):
        a = self._application
        row, _ = a._auth()
        c = a.owner._storage.connection
        fence = c.execute('SELECT fencing_token FROM writer_fences WHERE store_generation=?',
                          (a.owner._storage.generation,)).fetchone()
        return (a._db_stamp(), a._pin_raw(), bytes(row['row_digest']),
                bytes(fence[0]) if fence else None, a.owner._storage.restore_read_only)

    def _event(self, row):
        a = self._application
        m, obj = schema.parse_record(row['record'])
        require(hashlib.sha256(row['record']).digest() == row['record_digest'])
        require(m['scope'] == a._scope and m['scopeDigest'] == a._scope_id.hex() and
                m['storeGeneration'] == a.owner._storage.generation.hex() and
                m['keyContext'] == a._key_context.hex())
        plaintext = a.owner._provider.open(a._key, obj[1], obj[0], obj[2])
        require(len(plaintext) <= MAX_NOTE_BYTES)
        note = json.loads(plaintext)
        require(canonical(note) == plaintext and type(note) is dict and
                set(note) == {'title', 'body', 'titleConflicts'})
        require(type(note['title']) is str and type(note['body']) is str and
                type(note['titleConflicts']) is list and len(note['titleConflicts']) <= 32)
        require(len(note['title'].encode('utf-8')) <= 1024 and
                all(type(v) is str and len(v.encode('utf-8')) <= 1024 for v in note['titleConflicts']))
        return m, note

    def _replay_request(self, metadata, previous, state):
        """Reconstruct the original deterministic dependency traversal, not a new subset."""
        a = self._application
        c = a.owner._storage.connection
        changes, by_inner, slots = {}, {}, {}
        for item in metadata['inputs']:
            eid = bytes.fromhex(item['envelopeId'])
            row = c.execute('SELECT * FROM document_inputs WHERE scope=? AND envelope_id=?',
                            (a._scope_id, eid)).fetchone()
            require(row is not None and hashlib.sha256(row['record']).hexdigest() == item['digest'])
            obj = decode(row['record'])
            require(type(obj) is dict and set(obj) == {0, 1})
            change = a._record(eid, obj[0], obj[1], state, False)
            require(change.header[12].hex() == item['innerId'])
            slot = (change.actor, change.header[7])
            require(change.header[12] not in by_inner and slot not in slots)
            by_inner[change.header[12]] = eid
            slots[slot] = eid
            changes[eid] = change
        selected, visiting, ordered = set(), set(), []

        def visit(eid):
            require(eid in changes and eid not in visiting)
            if eid in selected:
                return
            require(len(selected) + len(visiting) < MAX_INPUTS)
            visiting.add(eid)
            for dependency in sorted(changes[eid].header[10]):
                require(dependency in by_inner)
                visit(by_inner[dependency])
            visiting.remove(eid)
            selected.add(eid)
            ordered.append(eid)

        roots = {bytes.fromhex(v) for v in metadata['targets']}
        if previous is not None:
            roots |= {bytes.fromhex(v['envelopeId']) for v in previous['inputs']}
        for root in sorted(roots):
            visit(root)
        require(selected == set(changes))
        request = {'profile': schema.PROFILE, 'schema': 'note-v1-local',
                   'changes': [changes[eid].descriptor() for eid in ordered],
                   'expectedHeads': metadata['heads']}
        require(digest(request) == metadata['coreRequestDigest'])
        return request

    def _validated_note(self, metadata, note, request):
        if self._engine is None:
            return None
        require(canonical(metadata['engine']) == canonical(self._engine))
        core = self._application._core
        if core is None:
            return None
        try:
            require(canonical(dict(core.identity)) == canonical(self._engine))
            report = core.materialize(request)
            require(canonical(dict(core.identity)) == canonical(self._engine))
            actual = check_materialization(request, report, self._engine, False)
            require(actual == canonical(note))
            return note
        except SharedChangeError as error:
            if error.code in UNAVAILABLE_CORE:
                return None
            raise

    def observe(self, operation_id: bytes | None = None):
        if operation_id is not None:
            require(type(operation_id) is bytes and len(operation_id) == 16, 'INVALID_INPUT')
        self._enter()
        pin = self.pin()
        self._busy = True
        a = self._application
        try:
            a._audit()
            if self._seen_frontier is not None:
                a._check_pin(self._seen_frontier)
            before = self._stamp()
            row, state = a._auth()
            c = a.owner._storage.connection
            rows = list(c.execute('SELECT * FROM document_apply_events WHERE scope=? ORDER BY revision',
                                  (a._scope_id,)))
            history = [(r, *self._event(r)) for r in rows]
            application = {'state': 'EMPTY', 'revision': 0, 'eventDigest': None, 'heads': [],
                           'inputCount': 0, 'evidenceClass': 'none', 'note': None,
                           'innerValidated': False, 'applied': False, 'recheckedCoreDigest': None}
            if history:
                event, meta, note = history[-1]
                application.update(revision=meta['revision'], eventDigest=event['record_digest'].hex(),
                                   heads=list(meta['heads']), inputCount=len(meta['inputs']),
                                   evidenceClass=meta['evidenceClass'])
                request = self._replay_request(meta, history[-2][1] if len(history) > 1 else None, state)
                if meta['evidenceClass'] == 'candidate':
                    application['state'] = 'CANDIDATE_ONLY'
                else:
                    application['state'] = 'CORE_RECHECK_REQUIRED'
                    visible = self._validated_note(meta, note, request)
                    if visible is not None:
                        application.update(state='VALIDATED_LOCAL_VIEW', note=visible,
                                           innerValidated=True, applied=True,
                                           recheckedCoreDigest=self._engine['digest'])
            operation = {'id': operation_id.hex() if operation_id is not None else None,
                         'state': 'NOT_QUERIED' if operation_id is None else 'NOT_OBSERVED',
                         'revision': None, 'eventDigest': None}
            if operation_id is not None:
                for event, meta, _ in history:
                    if event['operation_id'] == operation_id and meta['certificateDigest'] == pin['certificateDigest']:
                        operation.update(state='OBSERVED_CANDIDATE' if meta['evidenceClass'] == 'candidate'
                                         else 'OBSERVED_APPLICATION_RECORD', revision=meta['revision'],
                                         eventDigest=event['record_digest'].hex())
            require(before == self._stamp(), 'OBSERVATION_CHANGED')
            require(pin == self._pin_value(), 'SCOPE_MISMATCH')
            if application['innerValidated']:
                require(canonical(dict(a._core.identity)) == canonical(self._engine))
            require(not self._closed, 'OBSERVER_CLOSED')
            require(self._sequence < 2**64-1, 'SEQUENCE_EXHAUSTED')
            self._sequence += 1
            result = {'profile': PROFILE, **pin, 'sequence': str(self._sequence),
                      'observedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                      'authority': {'state': 'ACTIVE', 'controlHead': row['head'].hex(),
                                    'epoch': str(a._epoch), 'readerAuthorized': True},
                      'application': application, 'operation': operation,
                      'capabilities': {'observe': True, 'inspectApplication': True, 'sharedCommit': False,
                                       'sync': False, 'apply': False},
                      'restoreReadOnly': bool(a.owner._storage.restore_read_only),
                      'catalogComplete': False, 'replicationObserved': False, 'globalLatestProven': False,
                      'productQualified': False, 'evidenceKind': 'trusted-owner-application-observation'}
            result['revision'] = digest(result)
            self._seen_frontier = a._pin_raw()
            return result
        except ObservationError:
            raise
        except Exception:
            # Do not include key, text, raw payload or exception details in public errors.
            raise ObservationError('APPLICATION_READ_FAILED') from None
        finally:
            self._busy = False
