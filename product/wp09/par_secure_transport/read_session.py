"""TLS peer enrollment joined to existing current-authority signed read protocol.

No new signatures, crypto handshake, remote writes, ACKs or implicit receive.
One fresh TLS connection and existing signed challenge per explicit read.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import hmac
import re
import secrets
from .config import TransportError,pin
from .stream import TLSStream
from .framing import FramedChannel

def _exchange():
    # Keep the standalone TLS provider usable without loading Store/crypto.
    from product.wp04 import exchange
    return exchange

@dataclass(frozen=True,slots=True)
class PeerBinding:
    """Trusted owner enrollment, NOT learned from an unauthenticated peer."""
    peer_id: str
    certificate: bytes
    scope: tuple
    peer_sha256: str
    generation: int
    def __post_init__(self):
        if type(self.peer_id) is not str or re.fullmatch('[A-Za-z0-9_.:-]{1,128}',self.peer_id) is None:
            raise TransportError('PEER_BINDING')
        if type(self.certificate) is not bytes or not 1<=len(self.certificate)<=4096:
            raise TransportError('PEER_BINDING')
        if type(self.scope) not in (tuple,list):raise TransportError('SCOPE_BINDING')
        scope=tuple(self.scope)
        try:_exchange().scope_check(list(scope))
        except Exception:raise TransportError('SCOPE_BINDING') from None
        object.__setattr__(self,'scope',scope)
        pin(self.peer_sha256)
        if type(self.generation) is not int or not 0<=self.generation<2**63:
            raise TransportError('GENERATION_BINDING')

class ReadSession:
    """Consumes one TLS stream; uses Source only on its original owner thread."""
    def __init__(self,stream:TLSStream,source,binding:PeerBinding,current_generation):
        if type(stream) is not TLSStream:raise TransportError('TLS_REQUIRED')
        self.stream=stream;self.source=source;self.binding=binding
        self._generation=current_generation;self._used=False;self._frames=FramedChannel(stream)
        try:
            if type(binding) is not PeerBinding or type(source) is not _exchange().Source or not callable(current_generation):
                raise TransportError('PEER_BINDING')
            self._guard()
        except BaseException:stream.abort();raise

    def _guard(self):
        self.stream._check()
        return self._authority_guard()

    def _authority_guard(self):
        current=self._generation()
        if type(current) is not int or current!=self.binding.generation:raise TransportError('STALE_GENERATION')
        if tuple(self.source.scope)!=self.binding.scope:raise TransportError('SCOPE_BINDING')
        if not hmac.compare_digest(self.stream.peer_certificate_sha256,self.binding.peer_sha256):
            raise TransportError('TLS_PIN_BINDING')
        return self.source.authorize(self.binding.certificate)

    async def _run(self,action,cancel):
        if self._used:raise TransportError('SESSION_USED')
        self._used=True;task=None;watcher=None
        try:
            if cancel is not None and not isinstance(cancel,asyncio.Event):raise TransportError('INVALID_CANCEL')
            if cancel is not None and cancel.is_set():raise TransportError('CANCELLED')
            self._guard()
            if cancel is None:
                result=await action()
            else:
                task=asyncio.create_task(action());watcher=asyncio.create_task(cancel.wait())
                await asyncio.wait({task,watcher},return_when=asyncio.FIRST_COMPLETED)
                if cancel.is_set():raise TransportError('CANCELLED')
                result=task.result()
        except BaseException:self.stream.abort();raise
        finally:
            for child in (task,watcher):
                if child is not None and not child.done():child.cancel()
            if task is not None:await asyncio.gather(task,watcher,return_exceptions=True)
            await self.stream.close()
        # Cleanup itself awaits. Do not publish success against a generation or
        # authority that became stale during that final await.
        if cancel is not None and cancel.is_set():raise TransportError('CANCELLED')
        self._authority_guard()
        return result

    async def request(self,action,args,*,cancel=None):
        if self._used:raise TransportError('SESSION_USED')
        x=_exchange()
        try:
            x.request_args(action,args)
            owned_args=x.unpack(x.pack(args,x.MAX_REQUEST),x.MAX_REQUEST)
        except BaseException:
            self._used=True;self.stream.abort();await self.stream.close();raise
        async def operation():
            hello=await self._frames.receive(x.MAX_HELLO,guard=self._guard)
            public=self._guard()
            x.check_hello(self.source.p,public,list(self.binding.scope),hello)
            # Request creation encodes a bounded owned snapshot before I/O.
            request=x.make_request(self.source.p,self.source._seed,hello,self.source.certificate,action,owned_args)
            # Decode the signed request's own args so caller mutations during an
            # await cannot change which reply is accepted.
            request_body,_=x.split(request,x.MAX_REQUEST)
            frozen_action,frozen_args=request_body[4],request_body[5]
            await self._frames.send(request,x.MAX_REQUEST,guard=self._guard)
            response=await self._frames.receive(x.MAX_RESPONSE,guard=self._guard)
            public=self._guard()
            return x.check_response(self.source.p,public,hello,request,response,frozen_action,frozen_args)
        return await self._run(operation,cancel)

    async def serve(self,*,cancel=None):
        async def operation():
            x=_exchange()
            hello=x.make_hello(self.source.p,self.source._seed,list(self.binding.scope),
                               secrets.token_bytes(32),secrets.token_bytes(32),
                               max(50,min(30000,int(self.stream.remaining()*1000))))
            await self._frames.send(hello,x.MAX_HELLO,guard=self._guard)
            request=await self._frames.receive(x.MAX_REQUEST,guard=self._guard)
            cert,action,args=x.check_request(self.source,hello,request)
            if not hmac.compare_digest(cert,self.binding.certificate):raise TransportError('DEVICE_BINDING')
            self._guard()
            token=self.source.guard(cert)
            answer=self.source.answer(cert,action,args)
            if answer[0]!=token:raise TransportError('STALE_VIEW')
            response=x.make_response(self.source.p,self.source._seed,hello,request,True,answer)
            def response_guard():
                self._guard()
                if self.source.guard(cert)!=token:raise TransportError('STALE_VIEW')
            await self._frames.send(response,x.MAX_RESPONSE,guard=response_guard)
            return {'state':'SERVED_READ_ONLY','method':action,'application_applied':False}
        return await self._run(operation,cancel)
