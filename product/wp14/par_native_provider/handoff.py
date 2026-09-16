"""Owner-injected provider lifetime fence; no provider discovery or fallback."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Callable
from .model import ProviderDescriptor

class ProviderBlocked(RuntimeError): pass

@dataclass(frozen=True)
class ProviderBundle:
    descriptor:ProviderDescriptor
    pin_factory:Callable|None=None
    caller_factory:Callable|None=None
    connection_factory:Callable|None=None
    epoch_reader:Callable[[],str]|None=None
    def current_epoch(self):return self.descriptor.epoch if self.epoch_reader is None else self.epoch_reader()

class NativeProviderHandoff:
    def __init__(self,bundle:ProviderBundle|None):self.bundle=bundle
    def status(self):
        if self.bundle is None:return {'result':'BLOCKED','reason':'PROVIDER_NOT_SUPPLIED','productQualified':False}
        return {'result':'READY','reason':None,'providerId':self.bundle.descriptor.provider_id,'productQualified':False}
    def open(self,expected_epoch:str):
        if self.bundle is None:raise ProviderBlocked('PROVIDER_NOT_SUPPLIED')
        if expected_epoch!=self.bundle.descriptor.epoch:raise ValueError('PROVIDER_EPOCH')
        if self.bundle.current_epoch()!=expected_epoch:raise ValueError('PROVIDER_EPOCH_CHANGED')
        return ProviderSession(self.bundle,expected_epoch)

class ProviderSession:
    def __init__(self,bundle,epoch):self._bundle=bundle;self._epoch=epoch;self._closed=False;self._owned=[];self._retained=[];self._close_attempted=set()
    def _check(self):
        if self._closed:raise ValueError('SESSION_CLOSED')
        if self._bundle.current_epoch()!=self._epoch:raise ValueError('PROVIDER_EPOCH_CHANGED')
    def doctor(self):
        self._check();d=self._bundle.descriptor
        return {'result':'PASS','providerId':d.provider_id,'nativeBuild':d.native_build,'productQualified':False,'factoryCalls':0}
    def open_pin_store(self,binding):
        self._check()
        if self._bundle.pin_factory is None:raise ProviderBlocked('PIN_STORE_NOT_SUPPLIED')
        value=self._bundle.pin_factory(binding)
        if self._bundle.current_epoch()!=self._epoch:
            try:value.close()
            finally:raise ValueError('PROVIDER_EPOCH_CHANGED')
        return value
    def open_caller_store(self,binding):
        self._check()
        if self._bundle.caller_factory is None:raise ProviderBlocked('CALLER_STORE_NOT_SUPPLIED')
        value=self._bundle.caller_factory(binding)
        if self._bundle.current_epoch()!=self._epoch:raise ValueError('PROVIDER_EPOCH_CHANGED')
        return value
    async def connect(self,peer:str,cancel:asyncio.Event):
        self._check()
        if type(peer)is not str or not peer:raise ValueError('PEER_REQUIRED')
        if not isinstance(cancel,asyncio.Event):raise ValueError('CANCEL_EVENT_REQUIRED')
        if cancel.is_set():raise ValueError('CANCELLED')
        if self._bundle.connection_factory is None:raise ProviderBlocked('CONNECTION_FACTORY_NOT_SUPPLIED')
        c=await self._bundle.connection_factory(peer,cancel)
        async def reject(code):
            try:await c.close()
            finally:raise ValueError(code)
        if not callable(getattr(c,'close',None)):raise ValueError('CLOSE_REQUIRED')
        if getattr(c,'peer',None)!=peer:await reject('PEER_MISMATCH')
        if cancel.is_set():await reject('CANCELLED')
        if self._bundle.current_epoch()!=self._epoch:await reject('PROVIDER_EPOCH_CHANGED')
        self._owned.append(c);return c
    def connections(self):return tuple(self._owned)+tuple(self._retained)
    def status(self):
        return {'closed':self._closed,'owned':len(self._owned),'retained':len(self._retained),'cleanupComplete':not self._owned and not self._retained,'productQualified':False}
    async def close(self):
        if self._closed:return not self._owned and not self._retained
        self._closed=True
        for c in list(self._owned):
            key=id(c)
            if key in self._close_attempted:continue
            self._close_attempted.add(key)
            try:await c.close()
            except (Exception,asyncio.CancelledError):self._retained.append(c)
            finally:self._owned.remove(c)
        return not self._retained
