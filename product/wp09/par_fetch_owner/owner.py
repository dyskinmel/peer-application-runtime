"""One-loop, one-worker owner capability for explicit candidate fetch commands.

The caller owns Source/Store/Inbox and the cooperative ReadSession factory.
Possession of a private connected descriptor is the local transport capability;
JSON is not authorization. Apply is deliberately not in the operation set.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading

from product.runtime_read.fetch import FetchApplicationController
from product.wp04.contracts import canonical
from product.wp04.inbox import private_dir
from product.wp09.par_secure_fetch import FetchPlan, FetchClient
from product.wp09.par_secure_fetch.client import error_code
from product.wp09.par_secure_fetch.dependencies import DependencyPlanner
from product.wp09.par_secure_fetch.persistence import load_pinned, save_new
from product.wp10.events import EventError, need
from product.wp10.host import plain, MAX_RESPONSE
from par_store.fs import safe, sync_dir

PROTOCOL = 'par-owner-fetch-0049'
OPERATIONS = frozenset(('observe', 'propose', 'accept', 'resume', 'fetch', 'validate', 'inquire', 'close'))
READ_ONLY = frozenset(('observe', 'inquire', 'close'))
FIELDS = {
    'observe': (), 'close': (),
    'propose': ('expectedRevision',),
    'accept': ('expectedRevision', 'proposalId'),
    'resume': ('expectedRevision', 'planDigest'),
    'fetch': ('expectedRevision', 'planDigest'),
    'validate': ('expectedRevision',),
    'inquire': ('expectedRevision', 'operationId', 'expectedApplyRevision'),
}


def _hex(value, size=64):
    need(type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value) is not None, 'OWNER_SCHEMA')


def _args(operation, value):
    obj, _ = plain(value)
    required = {'context', *FIELDS[operation]}
    need(type(obj) is dict and set(obj) in (required, required | {'timeoutMs'}), 'OWNER_SCHEMA')
    for name in ('expectedRevision', 'proposalId', 'planDigest'):
        if name in obj: _hex(obj[name])
    if operation == 'inquire':
        _hex(obj['operationId'], 32)
        need(type(obj['expectedApplyRevision']) is int and 0 <= obj['expectedApplyRevision'] < 64, 'OWNER_SCHEMA')
    ms = obj.get('timeoutMs', 30000)
    need(type(ms) is int and 50 <= ms <= 120000, 'OWNER_SCHEMA')
    obj['timeoutMs'] = ms
    return obj


class FetchOwner:
    def __init__(self, root_plan, source, targets, current_generation, open_session, plan_directory,
                 *, application=None, proposal_seconds=30.0):
        need(callable(open_session), 'OWNER_FACTORY')
        need(type(proposal_seconds) in (int, float) and .05 <= proposal_seconds <= 60, 'OWNER_OPTIONS')
        self._loop = asyncio.get_running_loop()
        self._identity = (os.getpid(), threading.get_ident())
        self._controller = FetchApplicationController(root_plan, source, targets, current_generation,
                                                       application=application)
        self._root = root_plan
        self._source, self._generation, self._open = source, current_generation, open_session
        self._planner = DependencyPlanner(source, root_plan.binding, current_generation)
        self._directory = safe(Path(plan_directory)); private_dir(self._directory)
        self._pin = self._controller.pin()
        self._id = secrets.token_hex(16)
        self._channels = {}
        self._jobs = {}
        self._busy = False
        self._closed = False
        self._closed_event = asyncio.Event()
        self._proposal = None
        self._proposal_deadline = 0
        self._proposal_seconds = proposal_seconds
        self._selected = None
        self._client = None
        self._last_revision = None
        self._last_local = None
        self._resume_required = False

    def _thread(self):
        need((os.getpid(), threading.get_ident()) == self._identity and
             asyncio.get_running_loop() is self._loop, 'WRONG_OWNER')

    def _enter(self):
        self._thread(); need(not self._closed, 'OWNER_CLOSED')

    def _guard(self):
        try: return self._controller._guard()
        except Exception as exc: raise EventError(error_code(exc)) from None

    def stats(self):
        self._thread()
        return {'hostId': self._id, 'closed': self._closed, 'channels': len(self._channels),
                'inflight': len(self._jobs), 'cleanupComplete': not self._jobs,
                'proposalCount': int(self._proposal is not None)}

    def attach(self, *, allow_fetch=False):
        self._enter(); self._guard()
        need(type(allow_fetch) is bool, 'OWNER_OPTIONS')
        need(not self._channels and not self._jobs, 'OWNER_CHANNEL_LIMIT')
        channel = secrets.token_hex(16)
        self._channels[channel] = {'operations': OPERATIONS if allow_fetch else READ_ONLY, 'closed': False}
        return channel

    def context(self, channel):
        self._channel(channel)
        return plain(self._pin)[0]

    def _channel(self, channel):
        self._enter()
        need(type(channel) is str and channel in self._channels and not self._channels[channel]['closed'], 'OWNER_CHANNEL')
        return self._channels[channel]

    def detach(self, channel):
        self._thread()
        self._channels.pop(channel, None)
        self._proposal = None
        self._last_revision = None
        for future, (task, cancel, attached) in list(self._jobs.items()):
            if attached == channel:
                cancel.set()
                future.cancel()  # Never repeatedly Task.cancel the worker's cleanup.

    async def wait_closed(self):
        await self._closed_event.wait()

    async def close(self):
        """Bounded cooperative drain; caller must inspect cleanupComplete before closing Store."""
        self._thread(); self._closed = True; self._closed_event.set()
        for channel in list(self._channels): self.detach(channel)
        if self._jobs:
            tasks = [row[0] for row in self._jobs.values()]
            # asyncio.wait does not propagate cancellation or timeout into cleanup.
            await asyncio.wait(tasks, timeout=2.0)
        if not self._jobs:
            self._controller.close()
        return self.stats()

    def _check(self, channel, cancel, deadline):
        self._channel(channel); self._guard()
        need(not cancel.is_set(), 'CANCELLED')
        need(self._loop.time() < deadline, 'OWNER_DEADLINE')

    def _expected(self, value):
        need(value == self._last_revision and self._last_revision is not None, 'STALE_OBSERVATION')
        need(self._guard().hex() == self._last_local, 'LOCAL_VIEW_CHANGED')
        self._last_revision = None

    def _snapshot(self, channel, observation=None):
        if self._proposal is not None and (self._loop.time() >= self._proposal_deadline or
                self._proposal.local_revision != self._guard()):
            self._proposal = None
        observation = observation if observation is not None else self._controller.observe()
        self._last_revision = observation['revision']; self._last_local = observation['localRevision']
        proposal = None
        if self._proposal is not None:
            p = self._proposal; plan = p.plan
            proposal = {'id': p.digest, 'planDigest': None if plan is None else plan.digest,
                        'records': 0 if plan is None else len(plan.descriptors),
                        'bytes': 0 if plan is None else sum(d[2] for d in plan.descriptors), 'queries': p.queries}
        selection = None if self._selected is None else {'planDigest': self._selected.digest,
                       'records': len(self._selected.descriptors), 'bytes': sum(d[2] for d in self._selected.descriptors)}
        return plain({'profile': PROTOCOL, 'observation': observation, 'proposal': proposal,
                      'selection': selection, 'progress': None if self._client is None else self._client.progress(),
                      'resumeRequired': self._resume_required,
                      'operations': sorted(self._channels[channel]['operations'])}, MAX_RESPONSE)[0]

    def _selection_bytes(self, digest):
        return canonical({'profile': PROTOCOL, 'rootPlanDigest': self._root.digest,
                          'targetDigest': self._pin['targetDigest'], 'planDigest': digest})

    def _receipt_path(self, digest):
        data = self._selection_bytes(digest)
        return self._directory / ('selection-' + hashlib.sha256(data).hexdigest() + '.json'), data

    @staticmethod
    def _ensure_file(path, data):
        if path.exists():
            load_pinned(path, hashlib.sha256(data).hexdigest())
            # Re-observe and sync the exact bytes even after a response was lost.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try: os.fsync(fd)
            finally: os.close(fd)
            sync_dir(path.parent)
        else:
            save_new(path, data)

    def _persist(self, plan):
        # No automatic deletion/GC. Bound all entries, including orphan metadata.
        paths = [self._directory / (plan.digest+'.cbor'), self._receipt_path(plan.digest)[0]]
        count = 0
        with os.scandir(self._directory) as entries:
            for _ in entries:
                count += 1
                need(count <= 128, 'OWNER_PLAN_BUDGET')
        need(count + sum(not p.exists() for p in paths) <= 128, 'OWNER_PLAN_BUDGET')
        self._ensure_file(self._directory / (plan.digest+'.cbor'), plan.to_bytes())
        path, data = self._receipt_path(plan.digest)
        self._ensure_file(path, data)

    def _resume(self, digest):
        path, data = self._receipt_path(digest)
        load_pinned(path, hashlib.sha256(data).hexdigest())
        plan = FetchPlan.load(self._directory / (digest+'.cbor'), expected_sha256=digest)
        need(plan.binding == self._root.binding and plan.inbox_generation == self._root.inbox_generation,
             'PLAN_BINDING')
        self._persist(plan)
        return plan

    def request(self, channel, operation, args):
        row = self._channel(channel)
        need(type(operation) is str and operation in row['operations'], 'OWNER_OPERATION_DENIED')
        need(not self._busy, 'OWNER_BUSY')
        obj = _args(operation, args)
        need(obj['context'] == self._pin, 'OWNER_CONTEXT')
        self._guard()
        self._busy = True
        future = self._loop.create_future(); cancel = asyncio.Event()
        deadline = self._loop.time() + obj['timeoutMs']/1000
        # Keep strong ownership until all downstream cleanup finishes, not merely
        # until the caller's Future settles. Factories must cooperate with cancel.
        task = self._loop.create_task(self._run(channel, operation, obj, future, cancel, deadline))
        self._jobs[future] = (task, cancel, channel)
        def done(f):
            if f.cancelled(): cancel.set()
        future.add_done_callback(done)
        return future

    async def _run(self, channel, op, args, future, cancel, deadline):
        try:
            if future.cancelled(): cancel.set()
            self._check(channel, cancel, deadline)
            async with asyncio.timeout_at(deadline):
                value = await self._dispatch(channel, op, args, cancel)
            # Future callbacks can lag synchronous fsync/cleanup. Inspect its
            # cancellation bit directly before publishing a final success.
            if future.cancelled(): cancel.set()
            if op != 'close': self._check(channel, cancel, deadline)
            if not future.done(): future.set_result(value)
        except BaseException as exc:
            # This task is a boundary worker: cancellation is translated into the
            # caller Future only after downstream finally/cleanup has unwound.
            if isinstance(exc, asyncio.CancelledError): code = 'CANCELLED'
            elif isinstance(exc, TimeoutError): code = 'OWNER_DEADLINE'
            else: code = error_code(exc)
            self._last_revision = None
            self._proposal = None
            if op in ('accept', 'resume', 'fetch'): self._resume_required = True
            if not future.done(): future.set_exception(EventError(code))
        finally:
            self._jobs.pop(future, None)
            self._busy = False

    async def _dispatch(self, channel, op, args, cancel):
        if op == 'close':
            self._channels[channel]['closed'] = True
            self._proposal = None; self._last_revision = None
            return {'closed': True}
        if op == 'observe': return self._snapshot(channel)
        self._expected(args['expectedRevision'])
        observation = None
        if op == 'propose':
            self._proposal = None
            self._proposal = await self._planner.build(self._controller._targets, self._open,
                               timeout=args['timeoutMs']/1000, cancel=cancel)
            self._proposal_deadline = self._loop.time() + self._proposal_seconds
        elif op == 'accept':
            p = self._proposal
            need(p is not None and p.digest == args['proposalId'] and
                 self._loop.time() < self._proposal_deadline, 'PROPOSAL_UNAVAILABLE')
            self._proposal = None
            plan = p.accept(self._source, self._generation)
            self._selected = None; self._client = None
            if plan is not None:
                self._persist(plan)
                self._selected = plan
                self._client = FetchClient(plan, self._source, self._generation)
                self._client.reconcile()
            self._resume_required = False
        elif op == 'resume':
            plan = self._resume(args['planDigest'])
            client = FetchClient(plan, self._source, self._generation)
            client.reconcile()
            self._selected, self._client = plan, client
            self._proposal = None; self._resume_required = False
        elif op == 'fetch':
            need(not self._resume_required, 'RESUME_REQUIRED')
            need(self._selected is not None and self._selected.digest == args['planDigest'], 'PLAN_SELECTION')
            async def open_index(index): return await self._open()
            await self._client.execute(open_index, timeout=args['timeoutMs']/1000, cancel=cancel)
            self._proposal = None
        elif op == 'validate':
            observation = self._controller.validate(expected_revision=args['expectedRevision'])
        elif op == 'inquire':
            observation = self._controller.inquire(bytes.fromhex(args['operationId']),
                           expected_revision=args['expectedApplyRevision'],
                           expected_observation=args['expectedRevision'])
        return self._snapshot(channel, observation)
