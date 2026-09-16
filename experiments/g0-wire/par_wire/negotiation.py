"""Candidate transcript construction only. It does NOT verify certificates/signatures.

Transport peer IDs must come from the authenticated transport adapter, not merely
from incoming HELLO. See ADR-WIRE-0002 for the exact candidate byte layout.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import math
from .codec import encode
from .framing import decode_frame
from .errors import WireError


def domain(label: str, parts: list) -> bytes:
    if label not in ('session-auth','session-id'):
        raise WireError('DOMAIN')
    return encode(['PAR',1,label,parts])


@dataclass(frozen=True)
class Transcript:
    canonical: bytes
    candidate_session_id: bytes
    authenticated: bool = False

    def signing_bytes(self, role: str) -> bytes:
        if role not in ('initiator','responder'):
            raise WireError('ROLE')
        # Per-signer role proof prevents reflecting the initiator's AUTH as the responder's.
        return domain('session-auth',[self.canonical,role])

    def auth_digest(self, role: str) -> bytes:
        return hashlib.sha256(self.signing_bytes(role)).digest()


def build_transcript(initiator: bytes, responder: bytes, *, expected_profile: bytes,
                     expected_initiator_peer: bytes, expected_responder_peer: bytes,
                     selected_wire: str = 'par/1-draft-2', selected_suite: int = 1) -> Transcript:
    if type(expected_profile) is not bytes or len(expected_profile)!=32:
        raise WireError('PROFILE')
    for peer in (expected_initiator_peer,expected_responder_peer):
        if type(peer) is not bytes or not 1<=len(peer)<=128:
            raise WireError('TRANSPORT_BINDING')
    a,b=decode_frame(initiator),decode_frame(responder)
    if a[1]!=1 or b[1]!=1:
        raise WireError('MESSAGE_TYPE')
    aa,bb=a[4],b[4]
    if aa[0]!=bb[0]:raise WireError('APP_BINDING')
    if aa[5]!=expected_profile or bb[5]!=expected_profile:raise WireError('PROFILE')
    if aa[6]!=expected_initiator_peer or bb[6]!=expected_responder_peer:raise WireError('TRANSPORT_BINDING')
    if aa[6]==bb[6] or aa[2]==bb[2]:raise WireError('REFLECTION')
    # Draft-2 has one admitted version/suite. No preference algorithm or silent fallback.
    if selected_wire!='par/1-draft-2' or type(selected_suite) is not int or selected_suite!=1:
        raise WireError('NEGOTIATION')
    if any(selected_wire not in x[3] or selected_suite not in x[4] for x in (aa,bb)):
        raise WireError('NEGOTIATION')
    payload={0:1,1:aa[0],2:selected_wire,3:selected_suite,4:expected_profile,
             5:hashlib.sha256(initiator).digest(),6:hashlib.sha256(responder).digest(),
             7:aa[2],8:bb[2],9:aa[6],10:bb[6],11:'initiator',12:'responder'}
    canonical=encode(payload)
    candidate=hashlib.sha256(domain('session-id',[canonical])).digest()
    return Transcript(canonical,candidate)


class ReplayWindow:
    """Bounded local duplicate filter. No persistence or global replay guarantee.

    Call only after cryptographic verification before promoting a live session;
    otherwise unauthenticated input could fill the window. A full live window is
    backpressure, not permission to evict an unexpired entry. Reconnect uses a fresh
    local challenge; this filter is defense-in-depth, never the source of identity.
    """
    def __init__(self, *, capacity: int=4096, ttl: float=300):
        if type(capacity) is not int or not 1<=capacity<=1_000_000:
            raise ValueError('invalid replay capacity')
        if type(ttl) not in (int,float) or not math.isfinite(ttl) or ttl<=0:
            raise ValueError('invalid replay ttl')
        self.capacity=capacity;self.ttl=ttl;self._entries={};self._clock=None

    def remember(self, digest: bytes, *, now: float) -> None:
        if type(digest) is not bytes or len(digest)!=32:raise WireError('SCHEMA')
        if type(now) not in (int,float) or not math.isfinite(now) or (self._clock is not None and now<self._clock):
            raise WireError('CLOCK')
        self._clock=now
        self._entries={key:expiry for key,expiry in self._entries.items() if expiry>now}
        if digest in self._entries:raise WireError('REPLAY')
        if len(self._entries)>=self.capacity:raise WireError('RESOURCE_LIMIT')
        self._entries[digest]=now+self.ttl
