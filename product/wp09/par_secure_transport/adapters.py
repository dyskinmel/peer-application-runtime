"""Explicit TLS adapters for the existing owner-granted Connector.

The caller supplies the authenticated enrollment and trust files. This module
neither discovers peers nor enrolls certificates observed from the network.
"""
from __future__ import annotations
import asyncio
from dataclasses import replace
import hmac
import ipaddress
import socket
from types import MappingProxyType
from collections.abc import Mapping
from .config import TLSConfig, Limits, TransportError
from .stream import TLSStream
from .read_session import PeerBinding, _exchange
from ..par_connectivity import DialTarget, PeerProof

class TLSNumericDialer:
    supported_schemes = frozenset({'tcp'})

    def __init__(self, configs: Mapping[str, TLSConfig], *, limits: Limits | None = None):
        if not isinstance(configs, Mapping) or not 1 <= len(configs) <= 16:
            raise TransportError('TLS_CONFIG')
        owned = dict(configs)
        if any(type(k) is not str or not 1 <= len(k) <= 128 or
               type(v) is not TLSConfig or v.server_side for k,v in owned.items()):
            raise TransportError('TLS_CONFIG')
        self._configs = MappingProxyType(owned)
        self.limits = limits if limits is not None else Limits()
        if type(self.limits) is not Limits: raise TransportError('TLS_CONFIG')

    async def dial(self, target: DialTarget, cancel: asyncio.Event) -> TLSStream:
        if type(target) is not DialTarget or target.scheme != 'tcp':
            raise TransportError('TLS_TARGET')
        config = self._configs.get(target.peer_id)
        if config is None: raise TransportError('PEER_BINDING')
        if target.server_name is not None and target.server_name != config.server_hostname:
            raise TransportError('TLS_HOSTNAME')
        if not isinstance(cancel, asyncio.Event): raise TransportError('INVALID_CANCEL')
        if cancel.is_set(): raise TransportError('CANCELLED')
        if type(target.ip) is not str or '%' in target.ip:
            raise TransportError('TLS_TARGET')
        try: ip = ipaddress.ip_address(target.ip)
        except ValueError: raise TransportError('TLS_TARGET') from None
        if str(ip) != target.ip or type(target.port) is not int or not 1 <= target.port <= 65535:
            raise TransportError('TLS_TARGET')
        # Owner route policy is checked by Connector. No hostname enters this
        # socket call; even SNI comes from enrolled config, not the candidate.
        address = (str(ip),target.port) if ip.version == 4 else (str(ip),target.port,0,0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.limits.timeout
        sock = socket.socket(socket.AF_INET if ip.version == 4 else socket.AF_INET6, socket.SOCK_STREAM)
        sock.setblocking(False)
        task = loop.create_task(loop.sock_connect(sock,address))
        watcher = loop.create_task(cancel.wait())
        try:
            done,_ = await asyncio.wait({task,watcher},timeout=self.limits.timeout,return_when=asyncio.FIRST_COMPLETED)
            if cancel.is_set(): raise TransportError('CANCELLED')
            if task not in done: raise TransportError('TLS_DEADLINE')
            task.result()
            watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
            if cancel.is_set(): raise TransportError('CANCELLED')
            remaining = deadline-loop.time()
            if remaining < .001: raise TransportError('TLS_DEADLINE')
            result = await TLSStream.open(sock,config,limits=replace(self.limits,timeout=remaining),cancel=cancel)
            # There is deliberately no await between acquiring and returning
            # the exclusively owned stream.
            return result
        except BaseException as exc:
            for child in (task,watcher):
                if not child.done(): child.cancel()
            try: await asyncio.gather(task,watcher,return_exceptions=True)
            finally: sock.close()
            if isinstance(exc,(TransportError,asyncio.CancelledError)): raise
            if isinstance(exc,(OSError,TimeoutError)): raise TransportError('TLS_CONNECT_FAILED') from None
            raise

class TLSAuthenticator:
    """Actual TLS facts + trusted enrollment + current PAR read authority."""
    def __init__(self,source,bindings: Mapping[str,PeerBinding],current_generation):
        if type(source) is not _exchange().Source or not callable(current_generation):
            raise TransportError('PEER_BINDING')
        if not isinstance(bindings,Mapping) or not 1 <= len(bindings) <= 16:
            raise TransportError('PEER_BINDING')
        owned = dict(bindings)
        if any(type(b) is not PeerBinding or key != b.peer_id for key,b in owned.items()):
            raise TransportError('PEER_BINDING')
        self._source=source;self._bindings=MappingProxyType(owned);self._generation=current_generation

    async def authenticate(self,connection,expected_peer:str,scope_id:str,cancel:asyncio.Event) -> PeerProof:
        if type(connection) is not TLSStream: raise TransportError('TLS_REQUIRED')
        if not isinstance(cancel,asyncio.Event): raise TransportError('INVALID_CANCEL')
        if cancel.is_set(): raise TransportError('CANCELLED')
        if type(expected_peer) is not str: raise TransportError('PEER_BINDING')
        binding=self._bindings.get(expected_peer)
        if binding is None: raise TransportError('PEER_BINDING')
        connection._check()
        if type(scope_id) is not str or scope_id != binding.scope[1].hex() or tuple(self._source.scope) != binding.scope:
            raise TransportError('SCOPE_BINDING')
        current=self._generation()
        if type(current) is not int or current != binding.generation:
            raise TransportError('STALE_GENERATION')
        if not hmac.compare_digest(connection.peer_certificate_sha256,binding.peer_sha256):
            raise TransportError('TLS_PIN_BINDING')
        self._source.authorize(binding.certificate)
        return PeerProof(expected_peer,scope_id)
