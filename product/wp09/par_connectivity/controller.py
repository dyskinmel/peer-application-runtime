"""Finite explicit dial lifecycle, pinned destinations and late-result ownership.

No persistence, automatic reconnect/replay, fallback discovery or crypto. Ports
are trusted cooperative embedding capabilities, not a same-process sandbox.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable
from .model import (Attempt, Candidate, ConnectResult, ConnectivityError, PeerProof,
                    Policy, Resolution, identifier)
from .policy import authorize_addresses, numeric_ip, parse_endpoint, select_candidates
from .ports import Authenticator, Connection, Dialer, Resolver

@dataclass(eq=False)
class _Operation:
    generation: int
    deadline: float
    stop: asyncio.Event
    caller: asyncio.Event | None

TERMINAL = frozenset({'CLOSED','STALE_GENERATION','CANCELLED','DEADLINE',
                      'ATTEMPT_BUDGET','TOTAL_ADDRESS_BUDGET','CLEANUP_PENDING','CLEANUP_FAILED'})

class Connector:
    def __init__(self, policy: Policy, resolver: Resolver | None, dialer: Dialer | None,
                 authenticator: Authenticator | None, scope_id: str, *, metered: bool = False):
        if type(policy) is not Policy or type(metered) is not bool:
            raise ConnectivityError('INVALID_POLICY')
        self._scope = identifier(scope_id)
        self._loop = asyncio.get_running_loop()
        self._policy, self._resolver, self._dialer, self._auth = policy, resolver, dialer, authenticator
        self._metered = metered
        self._generation = 0
        self._closed = False
        self._operations: set[_Operation] = set()
        self._active: dict[int, Connection] = {}
        self._closing: dict[int, asyncio.Task] = {}
        self._lingering: set[asyncio.Task] = set()
        self._cleanup_failures = 0
        self._failed_resources: dict[int, Connection] = {}
        self._next_id = 1

    def _check_loop(self):
        if asyncio.get_running_loop() is not self._loop:
            raise ConnectivityError('WRONG_LOOP')

    def diagnostics(self) -> dict:
        return {'generation': self._generation, 'closed': self._closed,
                'inflight': len(self._operations), 'connections': len(self._active),
                'retiring': len(self._closing), 'lingering': len(self._lingering),
                'cleanup_failures': self._cleanup_failures,
                'failed_resources': len(self._failed_resources),
                'cleanup_complete': not (self._active or self._operations or self._closing or self._lingering or self._cleanup_failures)}

    def connection(self, connection_id: int) -> Connection:
        self._check_loop()
        if type(connection_id) is not int or connection_id not in self._active:
            raise ConnectivityError('CONNECTION_NOT_CURRENT')
        return self._active[connection_id]

    def _fence(self, op: _Operation):
        if self._closed:
            raise ConnectivityError('CLOSED')
        if op.generation != self._generation:
            raise ConnectivityError('STALE_GENERATION')
        if op.caller is not None and op.caller.is_set():
            raise ConnectivityError('CANCELLED')
        if self._loop.time() >= op.deadline:
            raise ConnectivityError('DEADLINE')
        if op.stop.is_set():
            raise ConnectivityError('CANCELLED')

    def _schedule_close(self, connection: Connection) -> asyncio.Task:
        key = id(connection)
        if key in self._closing:
            return self._closing[key]
        async def dispose():
            await connection.close()
        task = self._loop.create_task(dispose())
        self._closing[key] = task
        def completed(t):
            self._closing.pop(key, None)
            try:
                t.result()
            except (asyncio.CancelledError, Exception):
                self._cleanup_failures += 1
                # Do not lose ownership when a cooperative port reports failure.
                # Admission is latched closed; no automatic disposal retry.
                self._failed_resources[key] = connection
        task.add_done_callback(completed)
        return task

    async def _retire(self, connection: Connection):
        task = self._schedule_close(connection)
        # asyncio.wait does not cancel a slow close. Ownership remains visible.
        await asyncio.wait({task}, timeout=self._policy.cleanup_timeout)

    def _abandon(self, task: asyncio.Task, dispose: bool):
        self._lingering.add(task)
        def completed(t):
            self._lingering.discard(t)
            try:
                value = t.result()
            except (asyncio.CancelledError, Exception):
                return
            if dispose:
                self._schedule_close(value)
        task.add_done_callback(completed)
        if not task.done():
            task.cancel()

    async def _stage(self, call: Callable[[], Awaitable], op: _Operation,
                     stage: str, *, dispose: bool = False):
        self._fence(op)
        async def invoke():
            return await call()
        task = self._loop.create_task(invoke())
        watchers = [self._loop.create_task(op.stop.wait())]
        if op.caller is not None:
            watchers.append(self._loop.create_task(op.caller.wait()))
        try:
            try:
                done, _ = await asyncio.wait({task, *watchers}, timeout=max(0, op.deadline-self._loop.time()),
                                             return_when=asyncio.FIRST_COMPLETED)
                # Cancellation/generation wins even when a port finishes in the same tick.
                self._fence(op)
                if task not in done:
                    raise ConnectivityError('DEADLINE')
                try:
                    value = task.result()
                except (asyncio.CancelledError, Exception):
                    raise ConnectivityError(stage.upper() + '_FAILED') from None
            finally:
                for w in watchers:
                    w.cancel()
                await asyncio.gather(*watchers, return_exceptions=True)
        except BaseException:
            # Ownership is transferred only after watcher cleanup. Cancellation
            # of that cleanup must also retire a port's already-returned socket.
            op.stop.set()
            self._abandon(task, dispose)
            raise
        return value

    @staticmethod
    def _check_peer(connection: Connection, target):
        try:
            pair = connection.peername()
            valid = (type(pair) is tuple and len(pair) == 2 and type(pair[1]) is int and
                     str(numeric_ip(pair[0])) == target.ip and pair[1] == target.port)
        except Exception:
            valid = False
        if not valid:
            raise ConnectivityError('PEER_ADDRESS_MISMATCH')

    async def connect(self, candidates: tuple[Candidate, ...], *, purpose: str = 'user',
                      cancel: asyncio.Event | None = None) -> ConnectResult:
        self._check_loop()
        generation = self._generation
        attempts: list[Attempt] = []
        op = None
        try:
            if self._closed:
                raise ConnectivityError('CLOSED')
            if cancel is not None and not isinstance(cancel, asyncio.Event):
                raise ConnectivityError('INVALID_CANCEL')
            if purpose not in ('user', 'background'):
                raise ConnectivityError('INVALID_PURPOSE')
            if cancel is not None and cancel.is_set():
                raise ConnectivityError('CANCELLED')
            p = self._policy
            if self._cleanup_failures:
                raise ConnectivityError('CLEANUP_FAILED')
            if len(self._operations) + len(self._lingering) >= p.max_inflight:
                raise ConnectivityError('INFLIGHT_BUDGET')
            if len(self._active) + len(self._closing) + len(self._operations) + len(self._lingering) >= p.max_connections:
                raise ConnectivityError('CONNECTION_BUDGET')
            if self._metered and not (p.allow_metered_user if purpose == 'user' else p.allow_metered_background):
                raise ConnectivityError('METERED_DENIED')
            grants = select_candidates(candidates, p)
            if not grants:
                raise ConnectivityError('NO_CANDIDATES')
            op = _Operation(generation, self._loop.time()+p.timeout, asyncio.Event(), cancel)
            self._operations.add(op)
            return await self._connect(grants, p, op, attempts)
        except ConnectivityError as exc:
            return ConnectResult('LOCAL_ONLY', exc.code, generation, tuple(attempts))
        finally:
            if op is not None:
                self._operations.discard(op)

    async def _connect(self, grants, p, op, attempts):
        dial_count = 0
        address_count = 0
        reason = 'NO_ROUTE'
        for index, grant in enumerate(grants):
            self._fence(op)
            try:
                if grant.source == 'relay':
                    raise ConnectivityError('RELAY_UNAVAILABLE')
                endpoint = parse_endpoint(grant.endpoint)
                if self._dialer is None or endpoint.scheme not in self._dialer.supported_schemes:
                    raise ConnectivityError('ADAPTER_UNAVAILABLE')
                if self._auth is None:
                    raise ConnectivityError('AUTHENTICATOR_UNAVAILABLE')
                resolution = None
                if endpoint.literal is None:
                    if grant.resolver_id is None:
                        raise ConnectivityError('DNS_NOT_GRANTED')
                    if self._resolver is None:
                        raise ConnectivityError('RESOLVER_UNAVAILABLE')
                    resolution = await self._stage(lambda: self._resolver.resolve(endpoint.host, grant.resolver_id, op.stop), op, 'resolve')
                targets = authorize_addresses(grant, resolution, p, op.generation)
                address_count += len(resolution.addresses) if type(resolution) is Resolution else 1
                if address_count > p.max_total_addresses:
                    raise ConnectivityError('TOTAL_ADDRESS_BUDGET')
            except ConnectivityError as exc:
                reason = exc.code; attempts.append(Attempt(index, 'policy', reason))
                if reason in TERMINAL:
                    raise
                # Port failure does not authorize an implicit endpoint; only the
                # next candidate explicitly provided by the owner may be tried.
                op.stop = asyncio.Event()
                continue
            for target in targets:
                self._fence(op)
                if dial_count >= p.max_attempts:
                    raise ConnectivityError('ATTEMPT_BUDGET')
                dial_count += 1
                connection = None
                stage = 'dial'
                try:
                    connection = await self._stage(lambda: self._dialer.dial(target, op.stop), op, stage, dispose=True)
                    self._check_peer(connection, target)
                    stage = 'auth'
                    proof = await self._stage(lambda: self._auth.authenticate(connection, target.peer_id, self._scope, op.stop), op, stage)
                    self._fence(op)
                    self._check_peer(connection, target)
                    if type(proof) is not PeerProof or proof.peer_id != target.peer_id or proof.scope_id != self._scope:
                        raise ConnectivityError('AUTH_MISMATCH')
                    path = getattr(connection, 'observed_path', None)
                    if path not in ('direct', 'local-fixture'):
                        raise ConnectivityError('PATH_UNVERIFIED')
                    identity = self._next_id; self._next_id += 1
                    self._active[identity] = connection
                    connection = None  # ownership transferred exactly once
                    attempts.append(Attempt(index, 'auth', 'AUTHENTICATED'))
                    return ConnectResult('CONNECTED', 'AUTHENTICATED', op.generation,
                                         tuple(attempts), identity, path)
                except ConnectivityError as exc:
                    reason = exc.code; attempts.append(Attempt(index, stage, reason))
                    if reason in TERMINAL:
                        raise
                finally:
                    if connection is not None:
                        await self._retire(connection)
                if self._cleanup_failures:
                    raise ConnectivityError('CLEANUP_FAILED')
                if self._closing:
                    raise ConnectivityError('CLEANUP_PENDING')
                op.stop = asyncio.Event()
        raise ConnectivityError(reason)

    async def disconnect(self, connection_id: int) -> dict:
        self._check_loop()
        connection = self.connection(connection_id)
        del self._active[connection_id]
        await self._retire(connection)
        return self.diagnostics()

    async def _drain_active(self):
        connections = tuple(self._active.values())
        self._active.clear()
        for c in connections:
            self._schedule_close(c)
        if self._closing:
            await asyncio.wait(set(self._closing.values()), timeout=self._policy.cleanup_timeout)

    async def change_network(self, *, metered: bool, policy: Policy | None = None) -> dict:
        self._check_loop()
        if self._closed:
            raise ConnectivityError('CLOSED')
        if type(metered) is not bool or (policy is not None and type(policy) is not Policy):
            raise ConnectivityError('INVALID_POLICY')
        self._generation += 1
        self._metered = metered
        if policy is not None:
            self._policy = policy
        for op in self._operations:
            op.stop.set()
        await self._drain_active()
        return self.diagnostics()

    async def close(self) -> dict:
        self._check_loop()
        if not self._closed:
            self._closed = True
            self._generation += 1
            for op in self._operations:
                op.stop.set()
        await self._drain_active()
        return self.diagnostics()

    async def wait_for_cleanup(self) -> dict:
        self._check_loop()
        deadline = self._loop.time() + self._policy.cleanup_timeout
        while (self._operations or self._closing or self._lingering) and self._loop.time() < deadline:
            await asyncio.sleep(min(0.005, max(0, deadline-self._loop.time())))
        return self.diagnostics()
