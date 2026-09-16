"""Local receive preflight. Never emits APPLY_RESULT or applies inner CRDT data."""
from dataclasses import dataclass,field
from par_crypto import objects
from par_crypto.primitives import domain,hashed
from .common import parse,fixed,crypto
from .membership import member_certificate
from .errors import AuthError

@dataclass(frozen=True)
class ReceivedCandidate:
    envelope_id: bytes
    device_id: bytes
    object_id: bytes
    epoch: int
    payload: bytes=field(repr=False)
    inner_validated: bool=False
    applied: bool=False
    _permit: object=field(default=None,repr=False,compare=False)
    def recheck(self,state):state.validate_permit(self._permit)

def receive_change(state,raw,certificate,*,expected_object,expected_schema):
    state._thread_check();state._blocked();fixed(expected_object,32);fixed(expected_schema,32)
    revision=state.revision
    state.membership  # Force current control material first; never fall back to a stale role.
    o=parse('change-envelope',raw,786432);h=parse('change-header',o[0],16384)
    crypto(objects.change_header,h)
    if h[0]!=state.app_id or h[1]!=state.space_id or h[3]!=expected_object or h[9]!=expected_schema:raise AuthError('CONTEXT_MISMATCH')
    at=state.control(h[13]);historical=state.membership_at(at.id)
    cert=member_certificate(state._p,state.app_id,historical,certificate)
    did=hashed('device-id',[state.app_id,cert[3]])
    if did!=h[5]:raise AuthError('CERTIFICATE_BINDING')
    if historical.get(did).role!=2:raise AuthError('NOT_AUTHORIZED')
    if h[2]!=at.body[3]:raise AuthError('CONTEXT_MISMATCH')
    crypto(state._p.verify,cert[3],domain('envelope-sign',[o[0],o[1],o[2]]),o[3])
    if h[2]<state.epoch:raise AuthError('REBASE_REQUIRED')
    if h[2]!=state.epoch:raise AuthError('CONTROL_REQUIRED')
    permit=state.authorize(certificate,'write')
    plain=crypto(objects.open_change,state._p,state._active.secret,cert[3],h,raw)
    if state.revision!=revision:raise AuthError('STALE_DECISION')
    state.validate_permit(permit)
    return ReceivedCandidate(objects.envelope_id(raw),did,h[3],h[2],plain,_permit=permit)
