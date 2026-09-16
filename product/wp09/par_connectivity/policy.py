"""Finite grant selection and all-answer DNS validation; never performs I/O."""
from __future__ import annotations
import ipaddress
import re
from .model import (Candidate, ConnectivityError, DialTarget, Endpoint, Policy,
                    Resolution, RouteGrant, bounded_tuple)

# Conservative special-purpose exclusions, not a complete routability oracle.
# See CONNECTIVITY.ja.md: special ranges remain excluded even when an IANA
# sub-allocation is globally reachable. Do not depend on Python's is_private
# changing between runtime releases.
SPECIAL_V4 = tuple(ipaddress.ip_network(n) for n in (
    '0.0.0.0/8','100.64.0.0/10','169.254.0.0/16','192.0.0.0/24',
    '192.0.2.0/24','192.31.196.0/24','192.52.193.0/24','192.88.99.0/24',
    '192.175.48.0/24','198.18.0.0/15','198.51.100.0/24','203.0.113.0/24',
    '224.0.0.0/4','240.0.0.0/4'))
SPECIAL_V6 = tuple(ipaddress.ip_network(n) for n in (
    '2001::/23','2001:db8::/32','2002::/16','2620:4f:8000::/48','3fff::/20'))
LOCAL = tuple(ipaddress.ip_network(n) for n in (
    '10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','::1/128','fc00::/7'))
GLOBAL_V6 = ipaddress.ip_network('2000::/3')
# AWS IMDS ULA exception must not be admitted through a broad local grant.
METADATA_V6 = ipaddress.ip_address('fd00:ec2::254')
LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


def numeric_ip(text: str):
    if type(text) is not str or not text or len(text) > 45 or '%' in text:
        raise ConnectivityError('INVALID_ADDRESS')
    try:
        ip = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ConnectivityError('INVALID_ADDRESS') from exc
    return ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None else ip


def dns_name(text: str) -> str:
    if type(text) is not str or not text.isascii() or len(text) > 253:
        raise ConnectivityError('INVALID_ENDPOINT')
    name = text.lower()
    labels = name.split('.')
    if re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}', name):
        raise ConnectivityError('INVALID_ENDPOINT')
    # DNS labels ending in an all-numeric label may be interpreted as legacy IP
    # notation by system resolvers. Single labels, root dots and IDNA are not in
    # this candidate's owner-granted DNS profile.
    if len(labels) < 2 or not re.search(r'[a-z]', labels[-1]) or any(LABEL.fullmatch(x) is None for x in labels):
        raise ConnectivityError('INVALID_ENDPOINT')
    return name


def parse_endpoint(text: str) -> Endpoint:
    if type(text) is not str or not text.isascii() or len(text) > 320:
        raise ConnectivityError('INVALID_ENDPOINT')
    m = re.fullmatch(r'(tcp|quic|wss)://(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9.-]+):([1-9][0-9]{0,4})', text)
    if m is None or not 1 <= int(m[3]) <= 65535:
        raise ConnectivityError('INVALID_ENDPOINT')
    raw = m[2]
    bracketed = raw.startswith('[')
    host = raw[1:-1] if bracketed else raw
    try:
        ip = numeric_ip(host)
        if bracketed and ':' not in host:
            raise ConnectivityError('INVALID_ENDPOINT')
        host = str(ip)
        literal = host
    except ConnectivityError:
        if bracketed:
            raise ConnectivityError('INVALID_ENDPOINT') from None
        host = dns_name(host)
        literal = None
    return Endpoint(m[1], host, int(m[3]), literal)


def parse_network(text: str):
    if type(text) is not str or len(text) > 49 or '%' in text or '/' not in text:
        raise ConnectivityError('INVALID_NETWORK')
    try:
        return ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise ConnectivityError('INVALID_NETWORK') from exc


def _within(ip, networks) -> bool:
    return any(ip.version == n.version and ip in n for n in networks)


def address_allowed(text: str, grant: RouteGrant) -> str:
    ip = numeric_ip(text)
    if ip == METADATA_V6:
        raise ConnectivityError('METADATA_DENIED')
    if _within(ip, LOCAL):
        if not grant.allow_local:
            raise ConnectivityError('LOCAL_ADDRESS_DENIED')
    elif ip.version == 4:
        if _within(ip, SPECIAL_V4):
            raise ConnectivityError('SPECIAL_ADDRESS_DENIED')
    elif ip not in GLOBAL_V6 or _within(ip, SPECIAL_V6):
        raise ConnectivityError('SPECIAL_ADDRESS_DENIED')
    if not _within(ip, tuple(parse_network(n) for n in grant.networks)):
        raise ConnectivityError('ADDRESS_NOT_GRANTED')
    return str(ip)


def select_candidates(candidates, policy: Policy) -> tuple[RouteGrant, ...]:
    if type(policy) is not Policy:
        raise ConnectivityError('INVALID_POLICY')
    if not policy.allow_egress:
        raise ConnectivityError('EGRESS_DENIED')
    rows = bounded_tuple(candidates, policy.max_candidates, 'CANDIDATE_BUDGET') if type(candidates) in (list, tuple) else None
    if rows is None or any(type(c) is not Candidate for c in rows):
        raise ConnectivityError('INVALID_CANDIDATES')
    if sum(len(c.endpoint) + len(c.peer_id) + len(c.source) for c in rows) > policy.max_candidate_bytes:
        raise ConnectivityError('CANDIDATE_BYTES')
    available = {(g.source, g.peer_id, g.endpoint): g for g in policy.grants}
    seen = set()
    selected = []
    for c in rows:
        key = (c.source, c.peer_id, c.endpoint)
        if key not in available:
            raise ConnectivityError('ROUTE_NOT_GRANTED')
        if key not in seen:
            selected.append(available[key]); seen.add(key)
    return tuple(selected)


def authorize_addresses(grant: RouteGrant, resolution: Resolution | None,
                        policy: Policy, generation: int) -> tuple[DialTarget, ...]:
    e = parse_endpoint(grant.endpoint)
    if e.literal is not None:
        if resolution is not None:
            raise ConnectivityError('RESOLUTION_MISMATCH')
        addresses = (e.literal,)
    else:
        if grant.resolver_id is None:
            raise ConnectivityError('DNS_NOT_GRANTED')
        if type(resolution) is not Resolution:
            raise ConnectivityError('RESOLUTION_REQUIRED')
        if resolution.query != e.host or resolution.resolver_id != grant.resolver_id:
            raise ConnectivityError('RESOLUTION_MISMATCH')
        aliases = bounded_tuple(resolution.aliases, policy.max_aliases, 'DNS_ALIAS_BUDGET')
        seen = {e.host}
        for alias in aliases:
            name = dns_name(alias)
            if name in seen:
                raise ConnectivityError('DNS_ALIAS_CYCLE')
            if name not in grant.aliases:
                raise ConnectivityError('DNS_ALIAS_DENIED')
            seen.add(name)
        addresses = bounded_tuple(resolution.addresses, policy.max_addresses, 'ADDRESS_BUDGET')
        if not addresses:
            raise ConnectivityError('NO_ADDRESSES')
    # Validate the entire answer set before returning even the first target.
    ips = tuple(dict.fromkeys(address_allowed(a, grant) for a in addresses))
    return tuple(DialTarget(e.scheme, ip, e.port, e.host if e.literal is None else None,
                            grant.peer_id, grant.source, generation) for ip in ips)
