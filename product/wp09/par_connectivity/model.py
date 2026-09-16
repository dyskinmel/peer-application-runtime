"""Immutable owner inputs and finite observations. No wire or crypto protocol."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re

SOURCES = ('peer-cache', 'manual', 'lan', 'helper', 'relay')

class ConnectivityError(ValueError):
    """A stable, non-sensitive reason. Never embeds a route or adapter exception."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def identifier(value: str, code: str = 'INVALID_ID') -> str:
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) is None:
        raise ConnectivityError(code)
    return value

def bounded_tuple(value, limit: int, code: str) -> tuple:
    if type(value) not in (tuple, list) or len(value) > limit:
        raise ConnectivityError(code)
    return tuple(value)

@dataclass(frozen=True, slots=True)
class Endpoint:
    scheme: str
    host: str
    port: int
    literal: str | None
    @property
    def key(self) -> str:
        host = '[' + self.host + ']' if ':' in self.host else self.host
        return f'{self.scheme}://{host}:{self.port}'

@dataclass(frozen=True, slots=True)
class Candidate:
    endpoint: str
    peer_id: str
    source: str = 'manual'
    def __post_init__(self):
        from .policy import parse_endpoint
        object.__setattr__(self, 'endpoint', parse_endpoint(self.endpoint).key)
        identifier(self.peer_id)
        if type(self.source) is not str or self.source not in SOURCES:
            raise ConnectivityError('INVALID_SOURCE')

@dataclass(frozen=True, slots=True)
class RouteGrant:
    endpoint: str
    peer_id: str
    source: str
    networks: tuple[str, ...]
    allow_local: bool = False
    resolver_id: str | None = None
    aliases: tuple[str, ...] = ()
    def __post_init__(self):
        from .policy import parse_endpoint, parse_network, dns_name
        c = Candidate(self.endpoint, self.peer_id, self.source)
        object.__setattr__(self, 'endpoint', c.endpoint)
        if type(self.allow_local) is not bool:
            raise ConnectivityError('INVALID_POLICY')
        if self.resolver_id is not None:
            identifier(self.resolver_id, 'INVALID_RESOLVER')
        networks = bounded_tuple(self.networks, 32, 'INVALID_NETWORK')
        object.__setattr__(self, 'networks', tuple(str(parse_network(n)) for n in networks))
        aliases = bounded_tuple(self.aliases, 16, 'INVALID_ALIAS')
        object.__setattr__(self, 'aliases', tuple(dns_name(n) for n in aliases))

@dataclass(frozen=True, slots=True)
class Policy:
    grants: tuple[RouteGrant, ...] = ()
    allow_egress: bool = False
    allow_metered_user: bool = False
    allow_metered_background: bool = False
    max_candidates: int = 16
    max_candidate_bytes: int = 8192
    max_addresses: int = 8
    max_total_addresses: int = 32
    max_aliases: int = 4
    max_attempts: int = 4
    max_inflight: int = 2
    max_connections: int = 4
    timeout: float = 5.0
    cleanup_timeout: float = 0.25
    def __post_init__(self):
        grants = bounded_tuple(self.grants, 128, 'INVALID_POLICY')
        if any(type(g) is not RouteGrant for g in grants):
            raise ConnectivityError('INVALID_POLICY')
        keys = [(g.source, g.peer_id, g.endpoint) for g in grants]
        if len(keys) != len(set(keys)):
            raise ConnectivityError('DUPLICATE_GRANT')
        object.__setattr__(self, 'grants', grants)
        for name in ('allow_egress', 'allow_metered_user', 'allow_metered_background'):
            if type(getattr(self, name)) is not bool:
                raise ConnectivityError('INVALID_POLICY')
        maxima = {'max_candidates':128, 'max_candidate_bytes':65536, 'max_addresses':64,
                  'max_total_addresses':256, 'max_aliases':16, 'max_attempts':64,
                  'max_inflight':16, 'max_connections':64}
        for name, maximum in maxima.items():
            v = getattr(self, name)
            if type(v) is not int or not 1 <= v <= maximum:
                raise ConnectivityError('INVALID_BUDGET')
        for name in ('timeout', 'cleanup_timeout'):
            v = getattr(self, name)
            if type(v) not in (int, float) or not math.isfinite(v) or not 0.001 <= v <= 60:
                raise ConnectivityError('INVALID_BUDGET')

@dataclass(frozen=True, slots=True)
class Resolution:
    query: str
    resolver_id: str
    addresses: tuple[str, ...]
    aliases: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class DialTarget:
    scheme: str
    ip: str
    port: int
    server_name: str | None
    peer_id: str
    source: str
    generation: int

@dataclass(frozen=True, slots=True)
class PeerProof:
    peer_id: str
    scope_id: str

@dataclass(frozen=True, slots=True)
class Attempt:
    candidate_index: int
    stage: str
    reason: str

@dataclass(frozen=True, slots=True)
class ConnectResult:
    state: str
    reason: str
    generation: int
    attempts: tuple[Attempt, ...] = ()
    connection_id: int | None = None
    observed_path: str | None = None
    evidence: str = 'LOCAL_CANDIDATE_NOT_PRODUCT_QUALIFICATION'
