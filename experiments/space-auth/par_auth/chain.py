"""Single-thread-owned, bounded Space authority state. Signed roots are not payload semantics.

No implicit trust-on-first-use, fork winner, wall-clock ordering or durable DB.
State changes invalidate previously issued local permits. Private fields are
not a security boundary against hostile Python executing inside this process.
"""
from dataclasses import dataclass,field
import threading,hmac
from par_wire.codec import encode,decode
from par_crypto.primitives import domain,hashed,random_bytes
from .common import parse,fixed,app,crypto
from .membership import verify_membership,member_certificate
from .errors import AuthError
MAX_HISTORY_BYTES=768*1024

@dataclass(frozen=True)
class Control:
    raw: bytes
    body_bytes: bytes
    id: bytes
    authority_after: bytes
    anchor_id: bytes
    @property
    def body(self):return decode(self.body_bytes)

@dataclass(frozen=True)
class Permit:
    device_id: bytes
    role: int
    operation: str
    head: bytes
    epoch: int
    revision: int
    _owner: object=field(repr=False,compare=False)
    _stamp: object=field(repr=False,compare=False)
    _seal: bytes=field(repr=False,compare=False)

class AuthorityState:
    def __init__(self,provider,expected_app,expected_space,genesis,*,max_controls=1024):
        app(expected_app);fixed(expected_space,32)
        if type(max_controls) is not int or not 1<=max_controls<=1024:raise AuthError('SCHEMA_INVALID')
        o=parse('signed-object',genesis);b=parse('genesis-body',o[0])
        if b[1]!=expected_app or hashed('space-id',[o[0]])!=expected_space or o[1]!=b[2]:raise AuthError('TRUST_ANCHOR')
        crypto(provider.verify,b[2],domain('genesis-sign',[o[0]]),o[2])
        self._p=provider;self._app=expected_app;self._space=expected_space;self._genesis=genesis;self._genesis_body=o[0]
        self._thread=threading.get_ident();self._max_controls=max_controls;self._busy=False
        self._nodes={};self._sequences={};self._memberships={};self._resolved=set();self._head=expected_space
        self._revision=0;self._stamp=object();self._events=[];self._event_bytes=len(genesis)
        self._fork=();self._invalid=False;self._active=None
        self._key_checks={};self._permit_key=crypto(random_bytes,32)
    def _thread_check(self):
        if threading.get_ident()!=self._thread:raise AuthError('WRONG_THREAD')
        if self._busy:raise AuthError('REENTRANT_OPERATION')
    def _bump(self):self._revision+=1;self._stamp=object()
    def _capacity(self,weight):
        if self._event_bytes+weight>MAX_HISTORY_BYTES:raise AuthError('RESOURCE_BLOCKED')
    def _record(self,code,value,weight):self._events.append((code,value));self._event_bytes+=weight
    @property
    def app_id(self):return self._app
    @property
    def space_id(self):return self._space
    @property
    def head(self):return self._head
    @property
    def sequence(self):return len(self._sequences)
    @property
    def epoch(self):return self._nodes[self._head].body[3] if self._nodes else 0
    @property
    def revision(self):return self._revision
    @property
    def authority_public(self):return self._nodes[self._head].authority_after if self._nodes else decode(self._genesis_body)[2]
    @property
    def frozen(self):return bool(self._fork)
    @property
    def fork_evidence(self):return self._fork
    @property
    def active_epoch(self):return self._active.epoch if self._active is not None else None
    @property
    def membership(self):
        if self._head not in self._resolved:raise AuthError('MEMBERSHIP_REQUIRED')
        return self._memberships[self._nodes[self._head].body[6]]
    @property
    def epoch_anchor(self):
        if not self._nodes:raise AuthError('CONTROL_REQUIRED')
        return self._nodes[self._nodes[self._head].anchor_id]
    def control(self,head):
        fixed(head,32)
        if head not in self._nodes:raise AuthError('CONTROL_REQUIRED')
        return self._nodes[head]
    def membership_at(self,head):
        node=self.control(head)
        if head not in self._resolved:raise AuthError('MEMBERSHIP_REQUIRED')
        return self._memberships[node.body[6]]
    def _blocked(self):
        if self.frozen:raise AuthError('CONTROL_FORK')
        if self._invalid:raise AuthError('CONTROL_INVALID')
    def _inspect(self,raw):
        o=parse('control-entry',raw,66000);b=parse('control-body',o[0])
        if b[0]!=self._app or b[1]!=self._space:raise AuthError('CONTEXT_MISMATCH')
        seq=b[2]
        if seq<1:raise AuthError('CONTROL_SEQUENCE')
        if seq>self.sequence+1:raise AuthError('CONTROL_GAP')
        parent_id=self._space if seq==1 else self._sequences.get(seq-1)
        if b[4]!=parent_id:raise AuthError('CONTROL_PARENT')
        parent=self._nodes.get(parent_id);old=parent.body if parent else None
        pk=parent.authority_after if parent else decode(self._genesis_body)[2]
        if b[11]!=pk:raise AuthError('AUTHORITY_MISMATCH')
        crypto(self._p.verify,pk,domain('control-sign',[o[0]]),o[1])
        action=b[5];epoch=b[3]
        if any(b[i] is None for i in (8,9,10)):raise AuthError('MISSING_EPOCH_MATERIAL')
        if seq==1:
            gb=decode(self._genesis_body)
            if action!=1:raise AuthError('ACTION_INVALID')
            if epoch!=1:raise AuthError('EPOCH_SEQUENCE')
            if b[6]!=gb[4] or b[7]!=gb[5]:raise AuthError('GENESIS_ROOT')
        else:
            if action==1:raise AuthError('ACTION_INVALID')
            if epoch!=old[3]+(1 if action==3 else 0):raise AuthError('EPOCH_SEQUENCE')
            if action==3:
                # Compare all ancestors, not the competing same-position branch.
                history=[self._nodes[self._sequences[i]].body for i in range(1,seq)]
                if any(b[k]==p[k] for p in history for k in (8,9,10)):raise AuthError('EPOCH_MATERIAL_REUSED')
            else:
                keys=(8,9,10,13)+( (6,7) if action in (4,5) else () )
                if any(b[k]!=old[k] for k in keys):raise AuthError('ROOT_CHANGED')
        if action==4:
            if b[12] is None or b[12]==pk or 2 not in o:raise AuthError('ROTATION_PROOF')
            crypto(self._p.verify,b[12],domain('authority-possession',[o[0]]),o[2]);after=b[12]
        else:
            if b[12] is not None or 2 in o:raise AuthError('ROTATION_PROOF')
            after=pk
        cid=hashed('control-id',[raw]);anchor=cid if action in (1,3) else parent.anchor_id
        return Control(raw,o[0],cid,after,anchor)
    def observe(self,raw):
        self._thread_check()
        # Byte-exact replay is harmless even after a freeze; it never unfreezes.
        if type(raw) is bytes and any(n.raw==raw for n in self._nodes.values()):return 'DUPLICATE'
        self._blocked();self._busy=True
        try:
            node=self._inspect(raw);seq=node.body[2]
            if seq in self._sequences:
                self._fork=(self._nodes[self._sequences[seq]].raw,raw);self._record(1,raw,len(raw));self._bump()
                raise AuthError('CONTROL_FORK')
            self._capacity(len(raw))
            if self._nodes and self._head not in self._resolved:raise AuthError('MEMBERSHIP_REQUIRED')
            if len(self._nodes)>=self._max_controls:raise AuthError('RESOURCE_BLOCKED')
            self._nodes[node.id]=node;self._sequences[seq]=node.id;self._head=node.id
            self._record(1,raw,len(raw));self._bump();return 'OBSERVED'
        finally:self._busy=False
    def provide_membership(self,pages):
        self._thread_check();self._blocked()
        if not self._nodes:raise AuthError('CONTROL_REQUIRED')
        self._busy=True
        try:
            node=self._nodes[self._head];b=node.body;view=verify_membership(b[6],pages)
            if self._head in self._resolved:return 'DUPLICATE'
            size=sum(map(len,view.pages));self._capacity(size)
            self._record(2,view.pages,size)
            # Keep evidence of a correctly committed but invalid authority policy.
            self._memberships[view.root]=view
            if b[5] in (1,3) and not view.content_members:
                self._invalid=True;self._bump();raise AuthError('NO_CONTENT_RECIPIENT')
            if b[5]==2:
                previous=self.membership_at(b[4])
                if view.content_members!=previous.content_members:
                    self._invalid=True;self._bump();raise AuthError('CONTENT_MEMBERSHIP_CHANGED')
            self._resolved.add(self._head);self._bump();return 'VERIFIED'
        finally:self._busy=False
    def status(self):
        self._thread_check()
        state=('CONTROL_FORK' if self.frozen else 'CONTROL_INVALID' if self._invalid else
               'CONTROL_REQUIRED' if not self._nodes else 'MEMBERSHIP_PENDING' if self._head not in self._resolved else
               'EPOCH_PENDING' if self._active is None or self._active.anchor_id!=self.epoch_anchor.id else 'ACTIVE')
        return {'state':state,'known_head':self.head.hex(),'known_sequence':self.sequence,'known_epoch':self.epoch,
                'active_epoch':self.active_epoch,'authority_public':self.authority_public.hex(),'revision':self.revision,
                'freshness':'KNOWN_HISTORY_ONLY','seed_semantics':'OPAQUE_BYTES_NOT_CRDT_VALIDATED'}
    def authorize(self,certificate,operation):
        self._thread_check();self._blocked()
        if operation not in ('read','write','retain'):raise AuthError('OPERATION_INVALID')
        view=self.membership;body=member_certificate(self._p,self._app,view,certificate)
        did=hashed('device-id',[self._app,body[3]]);member=view.get(did)
        if member.role not in {'read':(1,2),'write':(2,),'retain':(3,)}[operation]:raise AuthError('NOT_AUTHORIZED')
        if operation!='retain' and (self._active is None or self._active.anchor_id!=self.epoch_anchor.id):raise AuthError('EPOCH_PENDING')
        seal=self._permit_seal(did,member.role,operation,self.head,self.epoch,self.revision)
        return Permit(did,member.role,operation,self.head,self.epoch,self.revision,self,self._stamp,seal)
    def _permit_seal(self,device,role,operation,head,epoch,revision):
        return hmac.digest(self._permit_key,encode([device,role,operation,head,epoch,revision]),'sha256')
    def validate_permit(self,permit):
        self._thread_check();self._blocked()
        if not isinstance(permit,Permit) or permit._owner is not self or permit._stamp is not self._stamp or permit.head!=self.head or permit.epoch!=self.epoch or permit.revision!=self.revision:raise AuthError('STALE_DECISION')
        try:expected=self._permit_seal(permit.device_id,permit.role,permit.operation,permit.head,permit.epoch,permit.revision)
        except Exception:raise AuthError('STALE_DECISION') from None
        if type(permit._seal) is not bytes or not hmac.compare_digest(expected,permit._seal):raise AuthError('STALE_DECISION')
    def activate(self,certificate,recipient_secret,package,package_ids,manifest,seeds):
        self._thread_check();self._blocked();self._busy=True
        try:
            from .activation import verify_activation
            candidate=verify_activation(self,certificate,recipient_secret,package,package_ids,manifest,seeds)
            check=hashed('auth-local/epoch-key-check',[candidate.secret])
            if candidate.epoch in self._key_checks and self._key_checks[candidate.epoch]!=check:raise AuthError('EPOCH_SECRET_CONFLICT')
            if any(epoch!=candidate.epoch and other==check for epoch,other in self._key_checks.items()):raise AuthError('EPOCH_SECRET_REUSED')
            self._key_checks[candidate.epoch]=check
            self._active=candidate;self._bump()
            return {'epoch':candidate.epoch,'seed_objects':len(candidate.seeds),'status':'ACTIVE_OPAQUE_SEEDS','automerge_validated':False}
        finally:self._busy=False
