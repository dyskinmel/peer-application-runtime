"""Bounded cooperative event owner loop. No executor, implicit ACK or listener.

The embedding owner opens EventJournal on this asyncio loop's thread and keeps
ownership of it. Futures/queues are loop-affine. A connected private descriptor
may be attached by transport.py; it is a capability supplied by that owner.
Wake tickets are volatile correlation, NOT signed state or durable cursors.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import os
import threading
from typing import Any

from .events import EventJournal, EventError, need, fixed, encode, random_bytes
from .sdk import EventOwnerPort, record

PROTOCOL = 'par-owner-event-host-0039'
MAX_REQUEST = 65536
MAX_RESPONSE = 1500000
OPERATIONS = frozenset(('open', 'poll', 'ack', 'cursor', 'cancel', 'wait'))


def plain(value: Any, limit: int = MAX_REQUEST) -> tuple[Any, int]:
    """Bounded builtin-only copy, rejecting cycles, floats and invalid Unicode."""
    count = 0
    size = 0
    seen: set[int] = set()

    def visit(v, depth):
        nonlocal count, size
        count += 1
        need(count <= 12000 and depth <= 12, 'HOST_INPUT_INVALID')
        if v is None or type(v) is bool:
            return v
        if type(v) is int:
            need(-(2**53 - 1) <= v <= 2**53 - 1, 'HOST_INPUT_INVALID')
            return v
        if type(v) is str:
            try: size += len(v.encode('utf-8'))
            except UnicodeError: raise EventError('HOST_INPUT_INVALID') from None
            need(size <= limit, 'HOST_INPUT_INVALID')
            return v
        need(type(v) in (dict, list) and id(v) not in seen and len(v) <= 4096, 'HOST_INPUT_INVALID')
        seen.add(id(v))
        try:
            if type(v) is list:
                return [visit(x, depth + 1) for x in v]
            out = {}
            for k, x in v.items():
                need(type(k) is str, 'HOST_INPUT_INVALID')
                visit(k, depth + 1)
                out[k] = visit(x, depth + 1)
            return out
        finally:
            seen.remove(id(v))
    result = visit(value, 0)
    raw = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    need(len(raw) <= limit, 'HOST_INPUT_INVALID')
    return result, len(raw)


@dataclass(eq=False)
class _Request:
    channel: str
    operation: str
    args: dict
    size: int
    future: asyncio.Future
    released: bool = False
    timer: asyncio.TimerHandle | None = None


@dataclass
class _Channel:
    port: EventOwnerPort
    ordinary: _Request | None = None
    cleanup: _Request | None = None
    last_empty_ticket: dict | None = None


class EventHost:
    """Cooperative bounded mailbox; all storage calls remain on the owner thread.

    request() snapshots/admit-or-rejects synchronously, and returns a Future.
    Queued cancellation prevents dispatch; cancellation after a synchronous
    effect starts cannot undo it. Existing SDK treats uncertain ACK as unknown.
    One normal request and one reserved cleanup request per connection. Pending
    waiters count against the global request limit but don't block dispatch.
    """
    def __init__(self, journal: EventJournal, *, max_channels=16, max_requests=32,
                 max_request_bytes=262144, turn_budget=4, heartbeat_seconds=.25,
                 wait_seconds=2.0):
        journal._enter()
        self._loop = asyncio.get_running_loop()
        self._identity = (os.getpid(), threading.get_ident())
        for n, lo, hi in ((max_channels, 1, 64), (max_requests, 1, 128),
                          (max_request_bytes, 1024, 1048576), (turn_budget, 1, 16)):
            need(type(n) is int and lo <= n <= hi, 'HOST_OPTIONS_INVALID')
        for t, hi in ((heartbeat_seconds, 5), (wait_seconds, 30)):
            need(type(t) in (int, float) and .01 <= t <= hi, 'HOST_OPTIONS_INVALID')
        self._j = journal
        self._max_channels, self._max_requests = max_channels, max_requests
        self._max_bytes, self._budget = max_request_bytes, turn_budget
        self._heartbeat_seconds, self._wait_seconds = heartbeat_seconds, wait_seconds
        self._host_id = random_bytes(16).hex()
        self._revision = 0
        self._channels: dict[str, _Channel] = {}
        self._queue: deque[_Request] = deque()
        self._cleanups: deque[_Request] = deque()
        self._waiters: dict[str, _Request] = {}
        self._requests = self._bytes = self._observations = 0
        self._peak_requests = self._peak_bytes = 0
        self._scheduled: asyncio.Handle | None = None
        self._heartbeat: asyncio.TimerHandle | None = None
        self._draining = False
        self._state = 'OPEN'
        self._closed_event = asyncio.Event()
        self._fault_code: str | None = None
        self._stamp = self._observe()

    def _owner(self):
        need((os.getpid(), threading.get_ident()) == self._identity, 'WRONG_OWNER')
        need(asyncio.get_running_loop() is self._loop, 'WRONG_OWNER_LOOP')

    def _enter(self):
        self._owner()
        need(self._state != 'CLOSED', 'HOST_CLOSED')
        if self._fault_code is not None: raise EventError(self._fault_code)

    def context(self, channel):
        self._enter()
        return self._channel(channel).port.context()

    def _channel(self, cid):
        need(type(cid) is str and cid in self._channels, 'HOST_CHANNEL_CLOSED')
        return self._channels[cid]

    def attach(self, consumer_id: bytes) -> str:
        self._enter(); fixed(consumer_id, 16)
        need(len(self._channels) < self._max_channels, 'HOST_CHANNEL_LIMIT')
        cid = random_bytes(16).hex()
        self._channels[cid] = _Channel(EventOwnerPort(self._j, consumer_id))
        return cid

    def _observe(self) -> bytes:
        self._observations += 1
        # Reuse the journal's authenticated full audit and current authority
        # fence, not stat/mtime or a remembered permit. No new persisted state.
        with self._j._operation() as stamp:
            result = encode([self._j._generation, self._j._known_tail, self._j._known_chain, stamp])
            self._j._recheck(stamp)
            return result

    def _ticket(self):
        return {'hostId': self._host_id, 'revision': str(self._revision)}

    def _wrap(self, value):
        return {'protocol': PROTOCOL, 'ticket': self._ticket(), 'result': value}

    def _refresh(self):
        try:
            stamp = self._observe()
            if stamp != self._stamp:
                need(self._revision < 2**64 - 1, 'HOST_GENERATION_EXHAUSTED')
                self._revision += 1; self._stamp = stamp
                for r in list(self._waiters.values()):
                    self._finish(r, self._wrap({'kind': 'wake', 'reason': 'changed'}))
        except Exception as e:
            self._state = 'FAILED'
            self._fault_code = e.code if isinstance(e, EventError) else 'HOST_OBSERVATION_FAILED'
            for r in list(self._waiters.values()): self._finish(r, error=EventError(self._fault_code))
            raise EventError(self._fault_code) from None

    def notify(self):
        """Owner calls this after local changes. Notification never ACKs data."""
        self._enter(); self._refresh()

    def publish(self, operation_id, payload, *, parents=(), cancelled=None):
        """Owner-only local publish. Not exposed through the subscription channel."""
        self._enter()
        try:
            receipt = self._j.publish(operation_id, payload, parents=parents, cancelled=cancelled)
        except BaseException:
            try: self._refresh()
            except EventError: pass
            raise
        try: self._refresh()
        except EventError:
            # A local commit may already exist; never report a clean response
            # after the host's final observation failed.
            raise EventError('EVENT_OUTCOME_UNKNOWN', operation_id) from None
        return receipt

    def request(self, channel: str, operation: str, args: dict) -> asyncio.Future:
        self._owner()
        need(self._state != 'CLOSED', 'HOST_CLOSED')
        need(type(operation) is str and operation in OPERATIONS, 'HOST_OPERATION_DENIED')
        if operation != 'cancel': self._enter()
        c = self._channel(channel)
        copied, size = plain(args)
        need(type(copied) is dict, 'HOST_INPUT_INVALID')
        cleanup = operation == 'cancel'
        if cleanup:
            need(c.cleanup is None, 'HOST_CHANNEL_BUSY')
        else:
            need(c.ordinary is None, 'HOST_CHANNEL_BUSY')
            need(self._requests < self._max_requests and self._bytes + size <= self._max_bytes, 'HOST_QUEUE_FULL')
        f = self._loop.create_future()
        r = _Request(channel, operation, copied, size, f)
        if cleanup:
            c.cleanup = r; self._cleanups.append(r)
        else:
            c.ordinary = r; self._queue.append(r)
            self._requests += 1; self._bytes += size
            self._peak_requests = max(self._peak_requests, self._requests)
            self._peak_bytes = max(self._peak_bytes, self._bytes)
        f.add_done_callback(lambda done: self._cancelled(r) if done.cancelled() else None)
        self._schedule()
        return f

    def _schedule(self):
        if self._scheduled is None and self._state != 'CLOSED' and not self._draining:
            self._scheduled = self._loop.call_soon(self._drain)

    def _release(self, r):
        if r.released: return
        r.released = True
        if r.timer: r.timer.cancel()
        if self._waiters.get(r.channel) is r: del self._waiters[r.channel]
        c = self._channels.get(r.channel)
        if r.operation == 'cancel':
            if c and c.cleanup is r: c.cleanup = None
        else:
            self._requests -= 1; self._bytes -= r.size
            if c and c.ordinary is r: c.ordinary = None
        if not self._waiters and self._heartbeat is not None:
            self._heartbeat.cancel(); self._heartbeat = None

    def _finish(self, r, value=None, error=None):
        self._release(r)
        if not r.future.done():
            if error is not None: r.future.set_exception(error)
            else: r.future.set_result(value)

    def _cancelled(self, r):
        if r.released: return
        self._release(r)
        q = self._cleanups if r.operation == 'cancel' else self._queue
        try: q.remove(r)
        except ValueError: pass

    def _drain(self):
        self._scheduled = None
        if self._state == 'CLOSED': return
        self._draining = True
        try:
            for _ in range(self._budget):
                q = self._cleanups if self._cleanups else self._queue
                if not q: break
                r = q.popleft()
                if r.future.cancelled() or r.released:
                    self._release(r); continue
                try: self._dispatch(r)
                except Exception as e:
                    code = e.code if isinstance(e, EventError) else 'HOST_OPERATION_FAILED'
                    self._finish(r, error=EventError(code))
        finally:
            self._draining = False
            if self._queue or self._cleanups: self._schedule()

    def _dispatch(self, r):
        c = self._channel(r.channel)
        if r.operation == 'cancel':
            # Cleanup remains possible after journal uncertainty: no read, ACK
            # or crypto operation is necessary to release a live subscription.
            record(r.args, ['sessionId'])
            need(type(r.args['sessionId']) is str and r.args['sessionId'] == c.port._session, 'SDK_SESSION_MISMATCH')
            need(c.port._sub is not None, 'SUBSCRIPTION_CLOSED')
            c.port._sub.cancel(); c.port._closed = True; c.last_empty_ticket = None
            if c.ordinary is not None:
                self._finish(c.ordinary, error=EventError('SUBSCRIPTION_CLOSED'))
            self._finish(r, self._wrap(c.port._base('cancelled')))
            return
        self._enter(); self._refresh()
        if r.operation == 'wait':
            c.port._enter(r.args, ['sessionId', 'ticket'])
            ticket = r.args['ticket']
            need(type(ticket) is dict and ticket == c.last_empty_ticket, 'WAKE_TICKET_INVALID')
            need(set(ticket) == {'hostId', 'revision'} and ticket['hostId'] == self._host_id, 'WAKE_TICKET_INVALID')
            v = ticket['revision']
            need(type(v) is str and v.isascii() and v.isdecimal() and str(int(v)) == v and int(v) <= self._revision, 'WAKE_TICKET_INVALID')
            c.last_empty_ticket = None
            if int(v) < self._revision:
                self._finish(r, self._wrap({'kind': 'wake', 'reason': 'changed'})); return
            self._waiters[r.channel] = r
            r.timer = self._loop.call_later(self._wait_seconds, self._wait_deadline, r)
            # Register first, then re-observe. No await/native owner turn occurs
            # between the final check and installing the waiter.
            self._refresh()
            self._arm_heartbeat()
            return
        method = {'open': c.port.open, 'poll': c.port.poll, 'ack': c.port.ack, 'cursor': c.port.cursor}[r.operation]
        before = self._ticket()
        value = method(r.args)
        self._refresh()
        result = self._wrap(value)
        if r.operation == 'poll':
            # Never label an empty result with a notification observed AFTER
            # that poll. Such a label could swallow an intervening publication.
            c.last_empty_ticket = dict(before) if not value['events'] else None
            if not value['events']: result['ticket'] = before
        self._finish(r, result)

    def _arm_heartbeat(self):
        if self._waiters and self._heartbeat is None and self._state == 'OPEN':
            self._heartbeat = self._loop.call_later(self._heartbeat_seconds, self._beat)

    def _beat(self):
        self._heartbeat = None
        if self._state != 'OPEN' or not self._waiters: return
        try: self._refresh()
        except EventError: return
        self._arm_heartbeat()

    def _wait_deadline(self, r):
        if r.released: return
        try:
            self._refresh()
            if not r.released: self._finish(r, self._wrap({'kind': 'wake', 'reason': 'deadline'}))
        except EventError: pass

    def detach(self, channel):
        self._owner(); c = self._channels.get(channel)
        if c is None: return
        if c.port._sub is not None: c.port._sub.cancel()
        for r in (c.ordinary, c.cleanup):
            if r is not None: self._finish(r, error=EventError('HOST_CHANNEL_CLOSED'))
        # Remove payload references immediately rather than retaining tombstones
        # until an arbitrary later turn; pending Future callbacks are bounded.
        self._queue = deque(r for r in self._queue if r.channel != channel)
        self._cleanups = deque(r for r in self._cleanups if r.channel != channel)
        del self._channels[channel]

    def stats(self):
        self._owner()
        return {'state': self._state, 'channels': len(self._channels), 'requests': self._requests,
                'request_bytes': self._bytes, 'waiters': len(self._waiters), 'observations': self._observations,
                'peak_requests': self._peak_requests, 'peak_request_bytes': self._peak_bytes,
                'hostId': self._host_id, 'revision': str(self._revision), 'automatic_ack': False}

    async def wait_closed(self):
        self._owner()
        await self._closed_event.wait()

    def close(self):
        self._owner()
        if self._state == 'CLOSED': return
        for cid in list(self._channels): self.detach(cid)
        self._state = 'CLOSED'
        self._closed_event.set()
        if self._scheduled: self._scheduled.cancel(); self._scheduled = None
        if self._heartbeat: self._heartbeat.cancel(); self._heartbeat = None
        # The embedding owner still owns journal and AuthorityStore lifetimes.
