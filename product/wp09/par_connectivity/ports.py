"""Trusted embedding ports. A route is not a peer or Space authentication proof."""
from __future__ import annotations
import asyncio
from typing import Protocol
from .model import DialTarget, PeerProof, Resolution

class Connection(Protocol):
    observed_path: str
    def peername(self) -> tuple[str, int]: ...
    async def close(self) -> None: ...

class Resolver(Protocol):
    async def resolve(self, host: str, resolver_id: str,
                      cancel: asyncio.Event) -> Resolution: ...

class Dialer(Protocol):
    supported_schemes: frozenset[str]
    async def dial(self, target: DialTarget, cancel: asyncio.Event) -> Connection: ...

class Authenticator(Protocol):
    # The embedding MUST actually authenticate the expected transport peer and
    # Space scope. Returning a PeerProof without that work does not grant trust.
    async def authenticate(self, connection: Connection, expected_peer: str,
                           scope_id: str, cancel: asyncio.Event) -> PeerProof: ...
