"""Complete bounded membership, not a standalone trust decision or Merkle proof."""
from dataclasses import dataclass
from par_crypto import objects
from par_crypto.primitives import hashed
from .common import canonical,parse,schema,fixed,app,crypto
from .errors import AuthError
PAGE_ENTRIES=64
MAX_MEMBERS=256

@dataclass(frozen=True)
class Member:
    device_id: bytes
    certificate_id: bytes
    role: int

@dataclass(frozen=True)
class Membership:
    root: bytes
    pages: tuple[bytes,...]
    members: tuple[Member,...]
    def get(self,device_id):return next((m for m in self.members if m.device_id==device_id),None)
    @property
    def content_members(self):return tuple(m for m in self.members if m.role in (1,2))

def build_membership(entries):
    if type(entries) is not list:raise AuthError('SCHEMA_INVALID')
    if len(entries)>MAX_MEMBERS:raise AuthError('RESOURCE_BLOCKED')
    for e in entries:schema('member-entry',e)
    values=sorted(entries,key=lambda x:x[0])
    if len({e[0] for e in values})!=len(values):raise AuthError('MEMBERSHIP_ORDER')
    return [canonical(values[i:i+PAGE_ENTRIES]) for i in range(0,len(values),PAGE_ENTRIES)]

def verify_membership(expected_root,pages):
    fixed(expected_root,32)
    if type(pages) is not list:raise AuthError('SCHEMA_INVALID')
    if len(pages)>MAX_MEMBERS//PAGE_ENTRIES:raise AuthError('RESOURCE_BLOCKED')
    owned=tuple(pages);entries=[];previous=None
    for i,raw in enumerate(owned):
        page=parse('member-page',raw,32768)
        if not 1<=len(page)<=PAGE_ENTRIES or (i<len(owned)-1 and len(page)!=PAGE_ENTRIES):raise AuthError('MEMBERSHIP_LAYOUT')
        for m in page:
            if previous is not None and m[0]<=previous:raise AuthError('MEMBERSHIP_ORDER')
            previous=m[0];entries.append(Member(m[0],m[1],m[2]))
    root=hashed('membership-root',[[hashed('member-page-id',[p]) for p in owned]])
    if root!=expected_root:raise AuthError('MEMBERSHIP_ROOT')
    return Membership(root,owned,tuple(entries))

def member_certificate(provider,app_id,membership,raw):
    """Account signer is trusted ONLY after the authority-pinned certificate digest matches."""
    app(app_id);outer=parse('signed-object',raw);body=parse('certificate-body',outer[0]);
    if body[1]!=app_id:raise AuthError('CONTEXT_MISMATCH')
    did=hashed('device-id',[app_id,body[3]]);member=membership.get(did)
    if member is None:raise AuthError('NOT_AUTHORIZED')
    if objects.certificate_id(raw)!=member.certificate_id:raise AuthError('CERTIFICATE_BINDING')
    return crypto(objects.verify_certificate,provider,app_id,body[2],raw)
