"""Read-only observations from the *already owned* authenticated local Store.

This is not a database server, CRDT interpreter, authorization token or replica
receipt. Only results of this device's local operations are exposed. The caller
is the trusted owner and provides the scope and local receipt key. Do not open
the writable AuthorityStore inside a web request just to construct this reader.
"""
from __future__ import annotations
import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone

from par_wire.codec import encode, decode
from par_store.model import fixed
from par_crypto.primitives import hashed, domain, hkdf_extract, hkdf_expand
from par_crypto.provider import bounded

PROFILE = 'par-reference-runtime-observation-v1'
MAX_STORE_ENVELOPES = 4096
MAX_DOCUMENT_ENVELOPES = 256

class ObservationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

class StoreObserver:
    """One process/thread and fixed scope. Methods neither write nor sign."""
    def __init__(self, owner, *, app_id, space_id, document_id, device_id, local_secret):
        try:
            for v in (space_id, document_id, device_id, local_secret): fixed(v, 32)
            if type(app_id) is not str or not 1 <= len(app_id.encode('utf8')) <= 128: raise ValueError()
        except Exception: raise ObservationError('INVALID_INPUT') from None
        self._owner = owner
        self._app = app_id
        self._space = space_id
        self._document = document_id
        self._device = device_id
        self._secret = local_secret
        self._identity = (os.getpid(), threading.get_ident())
        self._stream = secrets.token_hex(16)
        self._sequence = 0
        self._closed = False
        self._busy = False

    def _enter(self):
        if (os.getpid(), threading.get_ident()) != self._identity: raise ObservationError('WRONG_OWNER')
        if self._closed: raise ObservationError('OBSERVER_CLOSED')
        if self._busy: raise ObservationError('REENTRANT_OPERATION')
        self._owner._enter()

    def close(self):
        if (os.getpid(), threading.get_ident()) != self._identity: raise ObservationError('WRONG_OWNER')
        if self._busy: raise ObservationError('REENTRANT_OPERATION')
        # Releasing a Python reference is not a promise of secure memory erasure.
        self._secret = None
        self._closed = True

    def _local_key(self, purpose):
        generation = self._owner._storage.generation
        prk = hkdf_extract(hashed('crypto-local/salt', [generation]), self._secret)
        return hkdf_expand(prk, domain('crypto-local/key', [purpose]), 32)

    def _open_local(self, purpose, op, envelope, raw):
        # Same exact local format as CryptoStoreWriter. No signing/content key.
        bounded(raw, 600000, 1)
        obj = decode(raw, max_bytes=600000)
        if type(obj) is not dict or set(obj) != {0, 1, 2} or any(type(k) is not int for k in obj): raise ValueError()
        if type(obj[0]) is not int or obj[0] != 1: raise ValueError()
        fixed(obj[1], 24); bounded(obj[2], 524304, 16)
        aad = domain('crypto-local/record', [purpose, self._owner._storage.generation, op, envelope])
        return self._owner._provider.open(self._local_key(purpose), obj[1], aad, obj[2])

    def _inspect(self, operation_id):
        absent = {'id': operation_id.hex() if operation_id is not None else None,
                  'state': 'NOT_OBSERVED' if operation_id is not None else 'NOT_QUERIED',
                  'commitId': None, 'receiptVerified': False, 'outboxState': None}
        if operation_id is None: return absent
        c = self._owner._storage.connection
        row = c.execute('''SELECT l.*,m.encrypted_cache,m.store_generation,e.object_id,e.epoch,
               e.encrypted_bytes,a.device_id,o.state AS outbox_state
             FROM commit_ledger l JOIN local_commit_meta m USING(operation_id)
             JOIN envelopes e ON e.envelope_id=l.commit_id
             JOIN auth_commits a USING(operation_id)
             JOIN outbox o ON o.operation_id=l.operation_id AND o.envelope_id=l.commit_id
             WHERE l.operation_id=? AND l.space_id=? AND e.object_id=? AND a.device_id=?''',
             (operation_id, self._space, self._document, self._device)).fetchone()
        if row is None: return absent  # Also hides operations outside the configured scope.
        if row['store_generation'] != self._owner._storage.generation: raise ValueError()
        cache = self._open_local('cache', operation_id, row['commit_id'], row['encrypted_cache'])
        receipt = self._open_local('receipt', operation_id, row['commit_id'], row['receipt_encrypted'])
        expected = encode({0: operation_id, 1: row['input_digest'], 2: row['commit_id'],
                           3: row['store_generation'], 4: hashlib.sha256(cache).digest()})
        if receipt != expected: raise ValueError()
        if row['outbox_state'] not in ('pending','in-flight','retained','rebase-required'): raise ValueError()
        return {'id': operation_id.hex(), 'state': 'OBSERVED_COMMITTED', 'commitId': row['commit_id'].hex(),
                'receiptVerified': True, 'outboxState': row['outbox_state']}

    def _stamp(self):
        c = self._owner._storage.connection
        return (c.total_changes, c.execute('PRAGMA data_version').fetchone()[0],
                c.execute('PRAGMA schema_version').fetchone()[0],
                self._owner.pin(self._space), self._owner.status(self._space))

    def observe(self, operation_id=None):
        try:
            if operation_id is not None: fixed(operation_id, 16)
        except Exception: raise ObservationError('INVALID_INPUT') from None
        try: self._enter()
        except ObservationError: raise
        except Exception: raise ObservationError('STORE_UNAVAILABLE') from None
        self._busy = True
        try:
            c = self._owner._storage.connection
            if c.execute('SELECT count(*) FROM envelopes').fetchone()[0] > MAX_STORE_ENVELOPES: raise ObservationError('RESOURCE_LIMIT')
            before = self._stamp()
            if not self._owner.audit()['valid']: raise ObservationError('STORE_VERIFICATION_FAILED')
            row, state = self._owner._load(self._space)
            if row['app_id'] != self._app: raise ObservationError('SCOPE_MISMATCH')
            # No user-controlled SQL or row ordering enters the adapter.
            items = list(c.execute('''SELECT e.envelope_id,e.state FROM envelopes e JOIN commit_ledger l ON l.commit_id=e.envelope_id
                JOIN auth_commits a USING(operation_id) WHERE e.space_id=? AND e.object_id=? AND a.device_id=?
                ORDER BY e.envelope_id LIMIT ?''', (self._space, self._document, self._device, MAX_DOCUMENT_ENVELOPES+1)))
            if len(items) > MAX_DOCUMENT_ENVELOPES: raise ObservationError('RESOURCE_LIMIT')
            status = self._owner.status(self._space)
            role = 'none'
            try:
                membership = state.membership
                member = membership.get(self._device)
                if member is not None: role = {1:'reader',2:'editor',3:'none'}[member.role]
            except Exception:
                # Unknown current membership is not permission. History verification
                # was done above; status keeps the exact pending/fork condition.
                role = 'none'
            operation = self._inspect(operation_id)
            after = self._stamp()
            if before != after: raise ObservationError('OBSERVATION_CHANGED')
            if self._sequence >= 2**64-1: raise ObservationError('SEQUENCE_EXHAUSTED')
            self._sequence += 1
            raw = {'profile': PROFILE,
                'scope': {'appId': self._app, 'spaceId': self._space.hex(), 'documentId': self._document.hex()},
                'deviceId': self._device.hex(), 'storeGeneration': self._owner._storage.generation.hex(),
                'streamId': self._stream, 'sequence': str(self._sequence),
                'observedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
                'authority': {'state': status['state'], 'controlHead': status['known_head'], 'epoch': str(status['known_epoch']),
                    'role': role, 'writeAuthorized': status['state']=='ACTIVE' and role=='editor' and not status['restore_read_only']},
                'document': {'envelopeCount': len(items), 'pendingCount': sum(r['state']=='pending' for r in items),
                    'envelopeSetDigest': digest([r['envelope_id'].hex() for r in items]), 'text': None,
                    'innerValidated': False, 'applied': False, 'catalogComplete': False},
                'operation': operation,
                'capabilities': {'observe': True, 'inspectOperation': True, 'sharedCommit': False, 'sync': False, 'crdtApply': False},
                'restoreReadOnly': status['restore_read_only'], 'replicationObserved': False, 'globalLatestProven': False,
                'productQualified': False, 'evidenceKind': 'owner-verified-local-observation'}
            raw['revision'] = digest(raw)
            return raw
        except ObservationError: raise
        except Exception: raise ObservationError('STORE_VERIFICATION_FAILED') from None
        finally: self._busy = False
