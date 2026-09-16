"""Proof-of-possession requests and bounded retrieval admissions, NOT membership grants."""
from dataclasses import dataclass,field
from par_crypto import objects
from par_crypto.primitives import hashed,domain
from .common import parse,schema,fixed,crypto,app
from .errors import AuthError

@dataclass(frozen=True)
class VerifiedJoin:
    app_id: str
    space_id: bytes
    device_id: bytes
    certificate_id: bytes
    nonce: bytes
    role: int
    raw: bytes=field(repr=False)

@dataclass(frozen=True)
class RetrievalAdmission:
    device_id: bytes
    minimum_sequence: int
    role: int
    scope: str='BOUNDED_CONTROL_RETRIEVAL_ONLY'
    maximum_reply_bytes: int=131072

def _certificate(p,app_id,raw):
    outer=parse('signed-object',raw);body=parse('certificate-body',outer[0])
    if body[1]!=app_id:raise AuthError('JOIN_CONTEXT')
    # Self certificate consistency only; caller/operator still authorizes enrollment separately.
    return crypto(objects.verify_certificate,p,app_id,body[2],raw)

def create_join(p,device_seed,app_id,space_id,certificate,nonce,role):
    app(app_id);fixed(space_id,32);fixed(nonce,32)
    body=_certificate(p,app_id,certificate)
    if crypto(p.sign_public,device_seed)!=body[3]:raise AuthError('JOIN_CONTEXT')
    request={0:app_id,1:space_id,2:objects.certificate_id(certificate),3:nonce,4:role};schema('join-request-body',request)
    return crypto(objects._signed,p,device_seed,'join-request',request)

def verify_join(p,app_id,space_id,certificate,raw,expected_nonce,expected_role):
    app(app_id);fixed(space_id,32);fixed(expected_nonce,32)
    cert=_certificate(p,app_id,certificate);o=parse('signed-object',raw);b=parse('join-request-body',o[0])
    expected={0:app_id,1:space_id,2:objects.certificate_id(certificate),3:expected_nonce,4:expected_role};schema('join-request-body',expected)
    if b!=expected or o[1]!=cert[3]:raise AuthError('JOIN_CONTEXT')
    crypto(p.verify,cert[3],domain('join-request',[o[0]]),o[2])
    return VerifiedJoin(app_id,space_id,hashed('device-id',[app_id,cert[3]]),expected[2],expected_nonce,expected_role,raw)

def issue_admission(state,authority_seed,certificate,request,expected_nonce,expected_role,*,minimum_sequence):
    state._thread_check();state._blocked()
    if crypto(state._p.sign_public,authority_seed)!=state.authority_public:raise AuthError('AUTHORITY_MISMATCH')
    if type(minimum_sequence) is not int or not max(1,state.sequence)<=minimum_sequence<2**64:raise AuthError('ADMISSION_SEQUENCE')
    revision=state.revision
    req=verify_join(state._p,state.app_id,state.space_id,certificate,request,expected_nonce,expected_role)
    body={0:req.app_id,1:req.space_id,2:req.device_id,3:req.certificate_id,4:req.nonce,5:minimum_sequence,6:req.role}
    schema('admission-body',body)
    result=crypto(objects._signed,state._p,authority_seed,'admission-sign',body)
    if state.revision!=revision:raise AuthError('STALE_DECISION')
    return result

def verify_admission(p,trusted_authority,request,raw):
    fixed(trusted_authority,32)
    if not isinstance(request,VerifiedJoin):raise AuthError('ADMISSION_CONTEXT')
    o=parse('signed-object',raw);b=parse('admission-body',o[0])
    if o[1]!=trusted_authority:raise AuthError('AUTHORITY_MISMATCH')
    crypto(p.verify,trusted_authority,domain('admission-sign',[o[0]]),o[2])
    expected={0:request.app_id,1:request.space_id,2:request.device_id,3:request.certificate_id,4:request.nonce,6:request.role}
    if any(b[k]!=v for k,v in expected.items()):raise AuthError('ADMISSION_CONTEXT')
    if b[5]<1:raise AuthError('ADMISSION_SEQUENCE')
    return RetrievalAdmission(b[2],b[5],b[6])
