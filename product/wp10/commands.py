"""Owner-authorized local event commands, separate from the subscription port.

No keys or peer-supplied authorization are accepted over this surface. The trusted
embedding selects one already-open EventHost and grants publication per attached
private descriptor. The grant cannot exceed the journal's current write authority.
"""
from __future__ import annotations

import asyncio
from collections import deque
import copy
from dataclasses import dataclass
import hashlib
import re

from .events import EventError, decode, need, random_bytes, validate_payload
from .host import EventHost, MAX_REQUEST, plain
from .sdk import from_hex, record

PROTOCOL = 'par-local-event-commands-0040'
OPERATIONS = frozenset(('publish', 'inquire'))


def payload_from_wire(schema: dict, fields: dict) -> dict:
    """Validate canonical integer strings before converting to Python integers."""
    try:
        record(fields, schema)
        out = {}
        for name, kind in schema.items():
            field = fields[name]
            record(field, ('kind', 'value'))
            need(field['kind'] == kind, 'COMMAND_INPUT_INVALID')
            value = field['value']
            if kind in ('uint64', 'int64'):
                need(type(value) is str and len(value) <= 20 and
                     re.fullmatch(r'0|-?[1-9][0-9]*', value) is not None, 'COMMAND_INPUT_INVALID')
                number = int(value)
                need(0 <= number < 2**64 if kind == 'uint64' else -(2**63) <= number < 2**63,
                     'COMMAND_INPUT_INVALID')
                out[name] = number
            elif kind == 'bytes':
                need(type(value) is str and len(value) <= 32768 and len(value) % 2 == 0 and
                     re.fullmatch('[0-9a-f]*', value) is not None, 'COMMAND_INPUT_INVALID')
                out[name] = bytes.fromhex(value)
            else:
                need(type(value) is (str if kind == 'text' else bool), 'COMMAND_INPUT_INVALID')
                out[name] = value
        validate_payload(schema, out)  # Exact canonical encoded 16 KiB budget.
        return out
    except EventError as exc:
        if exc.code == 'RESOURCE_LIMIT': raise
        raise EventError('COMMAND_INPUT_INVALID') from None


@dataclass(eq=False)
class _Pending:
    channel: str
    operation: str
    args: dict
    size: int
    future: asyncio.Future
    released: bool = False


@dataclass
class _Attachment:
    context: dict
    allow_publish: bool
    pending: _Pending | None = None


class EventCommandHost:
    """Bounded cooperative command mailbox sharing the EventHost owner thread.

    At most one outstanding command per attachment; queue count/bytes reject
    synchronously. Cancellation of queued work prevents dispatch. Once synchronous
    SQLite/crypto starts, transport cancellation cannot preempt it. The journal's
    owner-side cancellation probe still observes cancellation at its defined fences.
    """
    def __init__(self, host: EventHost, *, max_channels=8, max_requests=16,
                 max_request_bytes=131072, turn_budget=2):
        host._enter()
        for value, low, high in ((max_channels, 1, 64), (max_requests, 1, 128),
                                 (max_request_bytes, 1024, 1048576), (turn_budget, 1, 16)):
            need(type(value) is int and low <= value <= high, 'HOST_OPTIONS_INVALID')
        self._host = host
        self._loop = asyncio.get_running_loop()
        self._max_channels, self._max_requests = max_channels, max_requests
        self._max_bytes, self._budget = max_request_bytes, turn_budget
        self._channels: dict[str, _Attachment] = {}
        self._queue: deque[_Pending] = deque()
        self._requests = self._bytes = self._peak_requests = self._peak_bytes = 0
        self._closed = False
        self._scheduled = None
        self._closed_event = asyncio.Event()
        self._watcher = self._loop.create_task(self._follow_owner())

    async def _follow_owner(self):
        try: await self._host.wait_closed()
        except asyncio.CancelledError: return
        self.close()

    def _enter(self):
        self._host._enter()
        need(not self._closed, 'HOST_CLOSED')

    def _channel(self, channel):
        need(type(channel) is str and channel in self._channels, 'HOST_CHANNEL_CLOSED')
        return self._channels[channel]

    def attach(self, *, allow_publish=False):
        self._enter()
        need(type(allow_publish) is bool, 'HOST_OPTIONS_INVALID')
        need(len(self._channels) < self._max_channels, 'HOST_CHANNEL_LIMIT')
        journal = self._host._j
        data = decode(journal._context)
        context = {'protocol': PROTOCOL, 'appId': data[1], 'spaceId': data[2].hex(),
                   'streamId': data[3].hex(), 'epoch': str(data[4]), 'schema': dict(journal._schema),
                   'schemaDigest': hashlib.sha256(data[5]).hexdigest(), 'issuer': journal._public.hex(),
                   'journalGeneration': journal._generation.hex(),
                   'authority': 'owner-publish' if allow_publish else 'inquire-only'}
        channel = random_bytes(16).hex()
        self._channels[channel] = _Attachment(context, allow_publish)
        return channel

    def context(self, channel):
        self._enter()
        return copy.deepcopy(self._channel(channel).context)

    def request(self, channel, operation, args):
        self._enter()
        need(type(operation) is str and operation in OPERATIONS, 'HOST_OPERATION_DENIED')
        attachment = self._channel(channel)
        need(attachment.pending is None, 'HOST_CHANNEL_BUSY')
        copied, size = plain(args, MAX_REQUEST)
        need(type(copied) is dict, 'COMMAND_INPUT_INVALID')
        need(self._requests < self._max_requests and self._bytes + size <= self._max_bytes, 'HOST_QUEUE_FULL')
        future = self._loop.create_future()
        pending = _Pending(channel, operation, copied, size, future)
        attachment.pending = pending
        self._queue.append(pending)
        self._requests += 1; self._bytes += size
        self._peak_requests = max(self._peak_requests, self._requests)
        self._peak_bytes = max(self._peak_bytes, self._bytes)
        future.add_done_callback(lambda f: self._cancel(pending) if f.cancelled() else None)
        self._schedule()
        return future

    def _schedule(self):
        if self._scheduled is None and not self._closed:
            self._scheduled = self._loop.call_soon(self._drain)

    def _release(self, pending):
        if pending.released: return
        pending.released = True
        self._requests -= 1; self._bytes -= pending.size
        attachment = self._channels.get(pending.channel)
        if attachment and attachment.pending is pending: attachment.pending = None
        pending.args = {}  # Drop plaintext references even when a done callback retains this record.

    def _cancel(self, pending):
        self._release(pending)
        try: self._queue.remove(pending)
        except ValueError: pass

    def _finish(self, pending, value=None, error=None):
        self._release(pending)
        if pending.future.done(): return
        if error is not None: pending.future.set_exception(error)
        else: pending.future.set_result(value)

    def _drain(self):
        self._scheduled = None
        for _ in range(self._budget):
            if self._closed or not self._queue: break
            pending = self._queue.popleft()
            if pending.released or pending.future.cancelled(): self._release(pending); continue
            try: self._finish(pending, self._execute(pending))
            except Exception as exc:
                code = exc.code if isinstance(exc, EventError) else 'HOST_OPERATION_FAILED'
                self._finish(pending, error=EventError(code))
        if self._queue: self._schedule()

    def _execute(self, pending):
        self._enter()
        attachment = self._channel(pending.channel)
        args = pending.args
        # An invalid/missing ID cannot be used as a correlation identity in a result.
        operation_id = from_hex(args.get('operationId'), 16)
        base = {'context': copy.deepcopy(attachment.context), 'hostId': self._host.stats()['hostId'],
                'operationId': operation_id.hex()}
        try:
            expected_keys = ('context', 'operationId', 'payload', 'parents') if pending.operation == 'publish' else ('context', 'operationId')
            record(args, expected_keys)
            need(type(args['context']) is dict and args['context'] == attachment.context, 'COMMAND_CONTEXT_MISMATCH')
            if pending.operation == 'inquire':
                receipt = self._host._j.inspect_operation(operation_id)
                if receipt is None: return base | {'kind': 'not-found-local'}
            else:
                need(attachment.allow_publish, 'COMMAND_NOT_AUTHORIZED')
                payload = payload_from_wire(self._host._j._schema, args['payload'])
                parents = args['parents']
                need(type(parents) is list and len(parents) <= 16, 'COMMAND_INPUT_INVALID')
                parents = [from_hex(p, 32) for p in parents]
                need(len(set(parents)) == len(parents), 'COMMAND_INPUT_INVALID')
                receipt = self._host.publish(operation_id, payload, parents=parents, cancelled=pending.future.cancelled)
            if receipt.state == 'CANCELLED':
                return base | {'kind': 'cancelled', 'phase': 'before-commit'}
            return base | {'kind': 'local-committed', 'sequence': str(receipt.sequence),
                           'eventId': receipt.event_id.hex(), 'replicated': False,
                           'cancellationRequested': receipt.cancellation_requested}
        except EventError as exc:
            if exc.code == 'EVENT_OUTCOME_UNKNOWN':
                return base | {'kind': 'outcome-unknown', 'code': 'LOCAL_OUTCOME_UNKNOWN'}
            # Journal errors other than EVENT_OUTCOME_UNKNOWN precede any uncertain
            # commit, or concern read-only inquiry. Never reinterpret transport errors.
            return base | {'kind': 'rejected', 'code': exc.code}

    def detach(self, channel):
        self._host._owner()
        attachment = self._channels.get(channel)
        if attachment is None: return
        if attachment.pending is not None:
            self._finish(attachment.pending, error=EventError('HOST_CHANNEL_CLOSED'))
        self._queue = deque(p for p in self._queue if p.channel != channel)
        del self._channels[channel]

    def stats(self):
        self._host._owner()
        return {'hostId': self._host.stats()['hostId'], 'closed': self._closed,
                'channels': len(self._channels), 'requests': self._requests, 'request_bytes': self._bytes,
                'peak_requests': self._peak_requests, 'peak_request_bytes': self._peak_bytes,
                'automatic_retry': False, 'automatic_ack': False}

    def close(self):
        self._host._owner()
        if self._closed: return
        for channel in list(self._channels): self.detach(channel)
        self._closed = True
        if self._scheduled: self._scheduled.cancel(); self._scheduled = None
        self._closed_event.set()
        if self._watcher is not asyncio.current_task(): self._watcher.cancel()

    async def wait_closed(self):
        self._host._owner()
        await self._closed_event.wait()
        if self._watcher is not asyncio.current_task():
            await asyncio.gather(self._watcher, return_exceptions=True)
