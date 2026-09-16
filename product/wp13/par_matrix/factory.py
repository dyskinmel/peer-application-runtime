"""One-shot conformance probe for explicitly supplied disposable factories.

The returned report is not an authentication or OS-security attestation. Pending
and failed cleanup keep strong references; a timeout cannot later become PASS.
"""
from __future__ import annotations
import asyncio
import math
from .pool import Factory

class FactoryRefusal(Exception):
    def __init__(self,code):
        if code not in ('CANCELLED','BUSY'):raise ValueError('REFUSAL_CODE')
        self.code=code;super().__init__(code)

class FactoryCheck:
    def __init__(self,factory:Factory|None,peer:str,probe):
        if factory is not None and not callable(factory):raise ValueError('FACTORY_REQUIRED')
        if type(peer)is not str or not 1<=len(peer)<=64 or not callable(probe):raise ValueError('PROBE_ARGUMENT')
        self.factory=factory;self.peer=peer;self.probe=probe;self._task=None
        self._stop=asyncio.Event();self._owned={};self._seen=[];self._attempted=set()
        self._checks=[];self._failure=None;self._started=False
    def status(self):
        pending=self._task is not None and not self._task.done()
        result=('BLOCKED'if self.factory is None else 'FAIL'if self._failure else
                'PASS'if self._task is not None and self._task.done() and len(self._checks)==5 and not self._owned else 'INCOMPLETE')
        return {'result':result,'reason':self._failure or ('FACTORY_NOT_SUPPLIED'if self.factory is None else None),
                'checks':list(self._checks),'pending':int(pending),'retained':len(self._owned),
                'cleanup_complete':not pending and not self._owned,'product_qualified':False,
                'scope':'DISPOSABLE_FACTORY_CONTRACT_ONLY'}
    def _fail(self,reason):
        if self._failure is None:self._failure=reason
        self._stop.set()
    def _keep(self,c):
        if any(c is old for old in self._seen):raise ValueError('DUPLICATE_CONNECTION')
        self._seen.append(c);self._owned[id(c)]=c
        if not callable(getattr(c,'close',None)):raise ValueError('CLOSE_REQUIRED')
        if getattr(c,'peer',None)!=self.peer:raise ValueError('PEER_MISMATCH')
        if self._stop.is_set():raise ValueError('PROBE_STOPPED')
        return c
    async def _close(self,c):
        key=id(c)
        if key in self._attempted:return
        self._attempted.add(key)
        await c.close()
        self._owned.pop(key,None)
    async def _exercise(self):
        try:
            first=self._keep(await self.factory(self.peer,self._stop));self._checks.append('create_bound_peer')
            if await self.probe(first) is not True:raise ValueError('READ_PROBE_FAILED')
            self._checks.append('read_probe')
            try:
                second=self._keep(await self.factory(self.peer,self._stop))
            except FactoryRefusal as exc:
                if exc.code!='BUSY':raise
            else:await self._close(second)
            self._checks.append('exclusive_or_distinct');await self._close(first)
            third=self._keep(await self.factory(self.peer,self._stop));await self._close(third);self._checks.append('recreate_and_close')
            cancelled=asyncio.Event();cancelled.set()
            try:extra=await self.factory(self.peer,cancelled)
            except FactoryRefusal as exc:
                if exc.code!='CANCELLED':raise
            else:
                self._keep(extra);raise ValueError('PRECANCEL_NOT_REJECTED')
            self._checks.append('precancel_rejected')
        except (Exception,asyncio.CancelledError) as exc:self._fail(type(exc).__name__+':'+str(exc)[:160])
        finally:
            for c in list(self._owned.values()):
                try:await self._close(c)
                except (Exception,asyncio.CancelledError) as exc:self._fail('CLEANUP_FAILED:'+type(exc).__name__)
    async def run(self,*,timeout=2.0):
        if self._started:raise ValueError('ALREADY_STARTED')
        self._valid_timeout(timeout);self._started=True
        if self.factory is None:return self.status()
        self._task=asyncio.create_task(self._exercise(),name='par-factory-conformance')
        return await self.finish(timeout=timeout)
    @staticmethod
    def _valid_timeout(timeout):
        if type(timeout) not in(int,float)or not math.isfinite(timeout)or not 0<=timeout<=120:raise ValueError('INVALID_TIMEOUT')
    async def finish(self,*,timeout=2.0):
        self._valid_timeout(timeout)
        if self._task and not self._task.done():
            try:
                _,pending=await asyncio.wait([self._task],timeout=timeout)
                if pending:self._fail('PROVIDER_DID_NOT_COMPLETE')
            except asyncio.CancelledError:
                self._fail('CALLER_CANCELLED');raise
        return self.status()
