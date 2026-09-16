"""Explicit local-experiment capability for an anchored application.

Embedding owns the controller, journal and PinStore. This service only owns its
channels/workers. No factory, key, path, target or provider is accepted from JSON.
Synchronous fsync/SQLite is not preempted by a remote cancellation packet.
"""
from __future__ import annotations
import asyncio
import hashlib
import os
import secrets
import threading
from product.wp09.par_application_intent import AnchoredApplication
from product.wp09.par_secure_fetch.client import error_code
from product.wp10.events import EventError, need
from product.wp10.host import plain, MAX_RESPONSE
from product.wp09.par_fetch_owner.owner import _hex

PROTOCOL = 'par-owner-application-0052'
OPERATIONS = frozenset(('observe', 'prepare', 'dispatch', 'inquire', 'retire', 'abandon', 'close'))
READ_ONLY = frozenset(('observe', 'inquire', 'close'))
FIELDS = {
    'observe': (), 'close': (),
    'prepare': ('expectedRevision', 'operationId', 'expectedApplyRevision', 'targetDigest'),
    'dispatch': ('expectedRevision', 'operationId', 'expectedApplyRevision', 'intentDigest'),
    'inquire': ('expectedRevision', 'operationId', 'expectedApplyRevision', 'intentDigest'),
    'retire': ('expectedRevision', 'operationId', 'expectedApplyRevision', 'intentDigest'),
    'abandon': ('expectedRevision', 'operationId', 'expectedApplyRevision', 'intentDigest'),
}


def arguments(op, value):
    obj, _ = plain(value)
    keys = {'context', *FIELDS[op]}
    need(type(obj) is dict and set(obj) in (keys, keys | {'timeoutMs'}), 'OWNER_SCHEMA')
    for key in ('expectedRevision', 'targetDigest'):
        if key in obj: _hex(obj[key])
    if op not in ('observe', 'close'):
        _hex(obj['operationId'], 32)
        n = obj['expectedApplyRevision']
        need(type(n) is int and 0 <= n < 64, 'OWNER_SCHEMA')
    if 'intentDigest' in obj and not (op == 'inquire' and obj['intentDigest'] is None):
        _hex(obj['intentDigest'])
    ms = obj.get('timeoutMs', 30000)
    need(type(ms) is int and 50 <= ms <= 120000, 'OWNER_SCHEMA')
    obj['timeoutMs'] = ms
    return obj


class ApplicationOwner:
    """One private channel/worker; mutation requires TWO embedding opt-ins.

    local_experiment is not evidence of an OS-safe provider. The product profile
    remains unavailable; a public RPC or default production apply is not added.
    """
    def __init__(self, application, *, local_experiment=False):
        need(type(application) is AnchoredApplication, 'ANCHORED_APPLICATION_REQUIRED')
        need(type(local_experiment) is bool, 'OWNER_OPTIONS')
        application._enter()
        self.application = application
        self._controller = application.controller
        self._local = local_experiment
        self._loop = asyncio.get_running_loop()
        self._identity = (os.getpid(), threading.get_ident())
        self._id = secrets.token_hex(16)
        self._closed = False
        self._closed_event = asyncio.Event()
        self._channels = {}
        self._jobs = {}
        self._context = {
            'profile': PROTOCOL, 'document': self._controller.pin(),
            'journalId': application.journal.pin().metadata_digest,
            'bindingDigest': hashlib.sha256(application.journal._binding).hexdigest(),
        }

    def _thread(self):
        need((os.getpid(), threading.get_ident()) == self._identity and
             asyncio.get_running_loop() is self._loop, 'WRONG_OWNER')

    def _enter(self):
        self._thread()
        need(not self._closed, 'OWNER_CLOSED')

    def _guard(self):
        try:
            self.application._enter()
            self.application._authority()
        except Exception as exc:
            raise EventError(error_code(exc)) from None

    def stats(self):
        self._thread()
        return {'hostId': self._id, 'closed': self._closed, 'channels': len(self._channels),
                'inflight': len(self._jobs), 'cleanupComplete': not self._jobs}

    def attach(self, *, allow_apply=False):
        self._enter(); self._guard()
        need(type(allow_apply) is bool, 'OWNER_OPTIONS')
        need(not allow_apply or self._local, 'LOCAL_EXPERIMENT_REQUIRED')
        need(not self._channels and not self._jobs, 'OWNER_CHANNEL_LIMIT')
        channel = secrets.token_hex(16)
        self._channels[channel] = OPERATIONS if allow_apply else READ_ONLY
        return channel

    def _channel(self, channel):
        self._enter()
        need(type(channel) is str and channel in self._channels, 'OWNER_CHANNEL')
        return self._channels[channel]

    def context(self, channel):
        self._channel(channel)
        return plain(self._context)[0]

    def detach(self, channel):
        self._thread()
        self._channels.pop(channel, None)
        self._controller._last = None  # A reattached capability needs a fresh observation.
        for future, (_, cancel, attached) in list(self._jobs.items()):
            if attached == channel:
                cancel.set(); future.cancel()

    async def wait_closed(self):
        await self._closed_event.wait()

    async def close(self):
        self._thread()
        self._closed = True; self._closed_event.set()
        for channel in list(self._channels): self.detach(channel)
        if self._jobs:
            await asyncio.wait([v[0] for v in self._jobs.values()], timeout=2.0)
        # Embedding, not this service, owns and closes journal/controller/PinStore.
        return self.stats()

    def _check(self, channel, future, cancel, deadline):
        if future.cancelled(): cancel.set()
        self._channel(channel); self._guard()
        need(not cancel.is_set(), 'CANCELLED')
        need(self._loop.time() < deadline, 'OWNER_DEADLINE')

    def _snapshot(self, channel, result=None):
        self._guard()
        j = self.application.journal
        current = j.current
        intent = None if current is None else {
            'operationId': current.operation_id.hex(), 'expectedRevision': current.expected_revision,
            'targets': [t.hex() for t in current.targets], 'digest': current.digest,
        }
        value = {'profile': PROTOCOL, 'context': self.context(channel),
                 'observation': self._controller.observe(),
                 'journal': self.application._result() if result is None else result,
                 'intent': intent, 'operations': sorted(self._channels[channel]),
                 'capability': 'LOCAL_EXPERIMENT' if self._local else 'READ_ONLY_UNQUALIFIED'}
        return plain(value, MAX_RESPONSE)[0]

    def request(self, channel, operation, args):
        operations = self._channel(channel)
        need(type(operation) is str and operation in operations, 'OWNER_OPERATION_DENIED')
        need(not self._jobs, 'OWNER_BUSY')
        obj = arguments(operation, args)
        need(obj['context'] == self._context, 'OWNER_CONTEXT')
        self._guard()
        future = self._loop.create_future(); cancel = asyncio.Event()
        deadline = self._loop.time() + obj['timeoutMs'] / 1000
        task = self._loop.create_task(self._run(channel, operation, obj, future, cancel, deadline))
        self._jobs[future] = (task, cancel, channel)
        future.add_done_callback(lambda f: cancel.set() if f.cancelled() else None)
        return future

    async def _run(self, channel, op, args, future, cancel, deadline):
        try:
            self._check(channel, future, cancel, deadline)
            result = self._dispatch(channel, op, args, cancel)
            if op != 'close': self._check(channel, future, cancel, deadline)
            if not future.done(): future.set_result(result)
        except BaseException as exc:
            code = 'CANCELLED' if isinstance(exc, asyncio.CancelledError) else error_code(exc)
            self._controller._last = None
            if not future.done(): future.set_exception(EventError(code))
        finally:
            self._jobs.pop(future, None)

    def _dispatch(self, channel, op, args, cancel):
        app = self.application
        if op == 'close':
            self._channels.pop(channel, None)
            return {'closed': True}
        if op == 'observe': return self._snapshot(channel)
        if op == 'prepare':
            need(args['targetDigest'] == self._context['document']['targetDigest'], 'APPLICATION_TARGETS')
            result = app.prepare(bytes.fromhex(args['operationId']),
                       expected_revision=args['expectedApplyRevision'], expected_observation=args['expectedRevision'])
        else:
            intent = app.journal.current
            need(intent is not None and intent.operation_id.hex() == args['operationId'] and
                 intent.expected_revision == args['expectedApplyRevision'], 'ORIGINAL_OPERATION_REQUIRED')
            dg = args['intentDigest']
            need(dg == intent.digest or op == 'inquire' and dg is None, 'INTENT_PIN')
            if op == 'dispatch':
                result = app.execute(intent.digest, expected_observation=args['expectedRevision'],
                                     timeout=args['timeoutMs'] / 1000, cancel=cancel)
            else:
                self._controller._command(args['expectedRevision'])
                result = getattr(app, op)(intent.digest)
        return self._snapshot(channel, result)
