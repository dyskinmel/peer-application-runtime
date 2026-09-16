"""Bounded, explicitly driven connection ownership for local diagnostics.

Factories and operations are trusted injections, not untrusted remote input.
Cancellation notifies an Event; it never repeatedly cancels cleanup. A caller's
outcome and actual resource ownership are independent. No automatic retries.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import math
import os
import re
import threading
from typing import Any, Awaitable, Callable, Protocol

class Connection(Protocol):
    peer: str
    async def close(self) -> None: ...

Factory = Callable[[str, asyncio.Event], Awaitable[Connection]]
Operation = Callable[[Connection, asyncio.Event], Awaitable[Any]]

@dataclass(frozen=True)
class Outcome:
    code: str
    value: Any = None
    detail: str | None = None

@dataclass
class _Job:
    peer: str
    identity: str
    factory: Factory | None
    operation: Operation | None
    result: asyncio.Future
    cancel_event: asyncio.Event
    deadline: float
    submitted: float
    timer: asyncio.TimerHandle | None = None
    started: float | None = None
    finished: float | None = None
    state: str = 'QUEUED'
    connection: Connection | None = None

class Request:
    """Read-only result handle; cancelling its await notifies, not kills, worker."""
    def __init__(self, pool: FairConnectionPool, job: _Job):
        self._pool, self._job = pool, job
    @property
    def identity(self) -> str: return self._job.identity
    @property
    def done(self) -> bool: return self._job.result.done()
    def cancel(self) -> bool: return self._pool.cancel(self.identity)
    async def wait(self) -> Outcome:
        self._pool._check()
        try: return await asyncio.shield(self._job.result)
        except asyncio.CancelledError:
            self.cancel()
            raise

class FairConnectionPool:
    """Per-peer FIFO with round-robin choice and one active owner per peer.

    max_active includes factory execution, operation, and close. A failed close
    poisons admission and retains its resource. An uncooperative provider can
    exhaust slots: status/cancel still run, but this is NOT an OS sandbox.
    Completed IDs cannot be reused in this pool. Recreate it after 4096 submits;
    durable idempotency remains the existing product's responsibility.
    """
    def __init__(self, peers, *, max_active=2, max_queued=32, per_peer=8):
        if (type(peers) not in (tuple,list) or not 1 <= len(peers) <= 8 or
                any(type(p) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,64}',p) is None for p in peers) or len(set(peers))!=len(peers)):
            raise ValueError('INVALID_PEERS')
        for n,limit in ((max_active,8),(max_queued,64),(per_peer,8)):
            if type(n) is not int or not 1 <= n <= limit: raise ValueError('INVALID_LIMIT')
        self._loop=asyncio.get_running_loop();self._identity=(os.getpid(),threading.get_ident())
        self._peers=tuple(peers);self._queues={p:deque() for p in peers};self._cursor=0
        self.max_active=max_active;self.max_queued=max_queued;self.per_peer=per_peer
        self._jobs:dict[str,_Job]={};self._workers:dict[str,asyncio.Task]={}
        self._busy:set[str]=set();self._owners:dict[int,_Job]={};self._retained:dict[str,_Job]={}
        self._closed=False;self._failed=False;self._peak_active=0;self._peak_queued=0

    def _check(self):
        if self._identity!=(os.getpid(),threading.get_ident()) or asyncio.get_running_loop() is not self._loop:
            raise ValueError('WRONG_OWNER')
    def _queued(self):return sum(map(len,self._queues.values()))
    def status(self):
        self._check()
        return {'submitted':len(self._jobs),'active':len(self._workers)+len(self._retained),
                'queued':self._queued(),'retained':len(self._retained),'closed':self._closed,'failed':self._failed,
                'peak_active':self._peak_active,'peak_queued':self._peak_queued,
                'cleanup_complete':not self._workers and not self._retained,
                'per_peer_queued':{p:len(q) for p,q in self._queues.items()}}
    def observations(self):
        self._check()
        return [{'id':j.identity,'peer':j.peer,'state':j.state,
                 'code':j.result.result().code if j.result.done() else None,
                 'queue_us':None if j.started is None else round((j.started-j.submitted)*1e6),
                 'lifetime_us':None if j.finished is None else round((j.finished-j.submitted)*1e6)} for j in self._jobs.values()]
    def submit(self, peer: str, identity: str, factory: Factory, operation: Operation, *, timeout=30.0) -> Request:
        self._check()
        if self._closed:raise ValueError('POOL_CLOSED')
        if self._failed:raise ValueError('POOL_FAILED')
        if type(peer) is not str or peer not in self._queues:raise ValueError('UNKNOWN_PEER')
        if type(identity) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}',identity) is None:raise ValueError('INVALID_ID')
        if identity in self._jobs:raise ValueError('DUPLICATE_ID')
        if not callable(factory):raise ValueError('FACTORY_REQUIRED')
        if not callable(operation):raise ValueError('OPERATION_REQUIRED')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .001<=timeout<=120:raise ValueError('INVALID_TIMEOUT')
        if len(self._jobs)>=4096:raise ValueError('SUBMISSION_BUDGET')
        if self._queued()>=self.max_queued:raise ValueError('QUEUE_FULL')
        if len(self._queues[peer])>=self.per_peer:raise ValueError('PEER_QUEUE_FULL')
        now=self._loop.time();j=_Job(peer,identity,factory,operation,self._loop.create_future(),asyncio.Event(),now+timeout,now)
        self._jobs[identity]=j;self._queues[peer].append(j)
        j.timer=self._loop.call_at(j.deadline,self._expire,identity)
        self._peak_queued=max(self._peak_queued,self._queued());self._pump();return Request(self,j)
    def _settle(self,j,code,value=None,detail=None):
        if not j.result.done():j.result.set_result(Outcome(code,value,detail))
    def _stop(self,j,reason):
        if j.result.done():return False
        j.cancel_event.set()
        if j.state=='QUEUED':
            self._queues[j.peer].remove(j);j.state='DONE';j.finished=self._loop.time()
            if j.timer:j.timer.cancel()
            j.factory=j.operation=None
            self._settle(j,reason+'_BEFORE_START');self._pump()
        else:self._settle(j,reason+'_AFTER_START')
        return True
    def cancel(self, identity: str) -> bool:
        self._check()
        if type(identity) is not str or identity not in self._jobs:raise ValueError('UNKNOWN_ID')
        return self._stop(self._jobs[identity],'CANCELLED')
    def _expire(self, identity):
        self._stop(self._jobs[identity],'TIMEOUT')
    def _pump(self):
        if self._closed or self._failed:return
        while len(self._workers)+len(self._retained)<self.max_active:
            chosen=None
            for step in range(len(self._peers)):
                i=(self._cursor+step)%len(self._peers);peer=self._peers[i]
                if self._queues[peer] and peer not in self._busy:
                    chosen=self._queues[peer].popleft();self._cursor=(i+1)%len(self._peers);break
            if chosen is None:break
            j=chosen;j.state='OPENING';j.started=self._loop.time();self._busy.add(j.peer)
            self._workers[j.identity]=self._loop.create_task(self._run(j),name='par-matrix-'+j.identity)
            self._peak_active=max(self._peak_active,len(self._workers)+len(self._retained))
    def _poison(self):
        self._failed=True
        for q in self._queues.values():
            while q:
                j=q.popleft();j.state='DONE';j.finished=self._loop.time();j.cancel_event.set()
                if j.timer:j.timer.cancel()
                j.factory=j.operation=None;self._settle(j,'POOL_FAILED')
    async def _run(self,j):
        result=Outcome('FACTORY_FAILED');owns=False;retain=False
        try:
            # Timer callbacks cannot preempt synchronous user code. Recheck before
            # invoking the factory as well as after awaited boundaries.
            if self._loop.time()>=j.deadline:self._expire(j.identity)
            if not j.cancel_event.is_set():
                connection=await j.factory(j.peer,j.cancel_event)
                if id(connection) in self._owners:
                    result=Outcome('DUPLICATE_CONNECTION');self._poison()
                else:
                    j.connection=connection;owns=True;self._owners[id(connection)]=j
                    if not callable(getattr(connection,'close',None)):
                        result=Outcome('INVALID_CONNECTION');retain=True;self._poison()
                    elif getattr(connection,'peer',None)!=j.peer:result=Outcome('PEER_MISMATCH')
                    else:
                        if self._loop.time()>=j.deadline:self._expire(j.identity)
                        if not j.cancel_event.is_set():
                            j.state='RUNNING'
                            try:result=Outcome('OK',await j.operation(connection,j.cancel_event))
                            except Exception as exc:result=Outcome('OPERATION_FAILED',detail=type(exc).__name__)
        except asyncio.CancelledError:
            j.cancel_event.set();result=Outcome('WORKER_CANCELLED')
        except Exception as exc:result=Outcome('FACTORY_FAILED',detail=type(exc).__name__)
        finally:
            if owns and not retain:
                j.state='CLOSING'
                try:await j.connection.close()
                except (Exception,asyncio.CancelledError) as exc:
                    result=Outcome('CLEANUP_FAILED',detail=type(exc).__name__);retain=True;self._poison()
            if j.timer:j.timer.cancel()
            if self._loop.time()>=j.deadline and not j.result.done():self._expire(j.identity)
            if retain:
                self._retained[j.identity]=j;j.state='CLEANUP_FAILED'
            else:
                if owns:self._owners.pop(id(j.connection),None)
                j.connection=None;self._busy.discard(j.peer);j.state='DONE'
            j.factory=j.operation=None;j.finished=self._loop.time()
            self._workers.pop(j.identity,None)
            self._settle(j,result.code,result.value,result.detail)
            self._pump()
    async def close(self, *, timeout=2.0) -> bool:
        self._check()
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<=timeout<=120:raise ValueError('INVALID_TIMEOUT')
        self._closed=True
        for j in self._jobs.values():self._stop(j,'CANCELLED')
        tasks=list(self._workers.values())
        if tasks:await asyncio.wait(tasks,timeout=timeout)
        return not self._workers and not self._retained
