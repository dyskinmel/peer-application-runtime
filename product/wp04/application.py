"""Bounded durable document application candidate, separate from ingestion.

The normal path requires an owner-pinned actual core. Synthetic mode persists
candidate-only records and NEVER claims semantic validation/applied. Same SQLite
transaction binds exact input bytes, materialization, frontier and operation ID.
No UI writes, automatic replay/GC, public transport or hostile-owner sandbox.
"""
from __future__ import annotations
import hashlib,hmac,json,os,sqlite3,threading
from dataclasses import dataclass,field
from pathlib import Path
from par_wire.codec import encode,decode
from par_blob_store import BlobStore
from par_auth.receiver import receive_change
from par_auth.membership import member_certificate
from par_crypto import objects
from par_crypto.primitives import domain,hkdf_extract,hkdf_expand,hashed,random_bytes
from par_store.model import u64
from par_store.store import sqlite_error
from par_store.errors import StoreError
from .contracts import (SharedChangeError,ChangeInput,Dependency,canonical,request_digest,
                         core_request,require,hex32,ids,MAX_CLOSURE_BYTES)
from . import application_schema as S
PROFILE=S.PROFILE
MAX_INPUTS=128
MAX_EVENTS=64
MAX_NONCES=512
MAX_NOTE_BYTES=262144
MAX_RECORD_BYTES=16*1024*1024

class ApplicationError(SharedChangeError):pass
def need(ok,code='INVALID_INPUT'):
 if not ok:raise ApplicationError(code)
def fixed(x,n):need(type(x) is bytes and len(x)==n)
def sha(x):return hashlib.sha256(x).digest()

class ApplicationStore(BlobStore):
 @classmethod
 def create(cls,root,*,provider,allow_unpatched_sqlite=False):
  return cls(S.ApplicationStorage.create(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite),provider)
 @classmethod
 def open(cls,root,*,provider,allow_unpatched_sqlite=False,expected_pins=()):
  self=cls(S.ApplicationStorage.open(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite),provider)
  try:
   need(self.audit()['valid'],'APPLICATION_CORRUPT');self._check_pins(expected_pins)
   if not self._storage.restore_read_only:
    for r in list(self._storage.connection.execute("SELECT space_id FROM auth_spaces WHERE phase='ACTIVE'")):
     row,st=self._load(r[0]);self._persist(row,st,None)
   return self
  except BaseException:self.close();raise
 def audit(self):
  base=super().audit();errors=list(base['errors']);errors+=S.audit_records(self._storage.connection,self._storage.generation)
  return dict(base,valid=not errors,errors=sorted(set(errors)),scope='SIGNED_INGESTION_AND_STRUCTURAL_APPLICATION_BINDINGS',application_aead_checked=False,automerge_validated=False)
 @classmethod
 def migrate_v3(cls,root,*,provider,allow_unpatched_sqlite=False,observer=None):
  with BlobStore.open(Path(root),provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as old:
   need(old.audit()['valid'],'APPLICATION_CORRUPT');old._enter(True);c=old._storage.connection;attempted=False
   try:
    c.execute('BEGIN IMMEDIATE')
    if observer:observer('apply_migration.after_begin')
    for statement in S.statements():c.execute(statement)
    if observer:observer('apply_migration.after_schema')
    c.execute('UPDATE store_metadata SET profile_digest=?',(S.digest(),));c.execute('PRAGMA user_version=4')
    if observer:observer('apply_migration.before_commit')
    attempted=True;c.execute('COMMIT')
    if observer:observer('apply_migration.after_commit')
   except BaseException as e:
    if c.in_transaction:c.execute('ROLLBACK')
    if attempted:raise ApplicationError('MIGRATION_OUTCOME_UNKNOWN') from None
    if isinstance(e,sqlite3.Error):raise sqlite_error(e) from None
    raise
  return cls.open(root,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite)
 @classmethod
 def restore_snapshot(cls,source,dest,*,provider,allow_unpatched_sqlite=False):
  from par_store.recovery import restore_snapshot
  def validate(stage):
   with cls.open(stage,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as view:need(view.audit()['valid'],'APPLICATION_CORRUPT')
  return restore_snapshot(Path(source),Path(dest),allow_unpatched_sqlite=allow_unpatched_sqlite,store_type=S.ApplicationStorage,stage_validator=validate)

@dataclass(frozen=True)
class PreparedApplication:
 operation_id:bytes
 targets:tuple[bytes,...]
 expected_revision:int
 metadata:bytes=field(repr=False)
 ciphertext:bytes=field(repr=False)
 nonce:bytes=field(repr=False)
 records:tuple=field(repr=False)
 authority_digest:bytes=field(repr=False)
 source_digest:bytes=field(repr=False)
 writer_fence:bytes=field(repr=False)
 _owner:object=field(repr=False,compare=False)
 _seal:bytes=field(repr=False,compare=False)


def check_materialization(request,report,engine,allow_double):
 keys={'profile','requestDigest','engine','schema','changes','appliedHashes','heads','missing','note'}
 need(type(report) is dict and set(report)==keys,'CORE_REPORT_INVALID')
 need(report['profile']==PROFILE and report['schema']=='note-v1-local' and report['requestDigest']==request_digest(request),'CORE_CONTEXT_MISMATCH')
 need(type(report['engine']) is dict and canonical(report['engine'])==canonical(engine),'CORE_IDENTITY_CHANGED')
 expected=[{k:x[k] for k in ('actor','sequence','hash','dependencies')} for x in request['changes']]
 need(type(report['changes']) is list and canonical(report['changes'])==canonical(expected),'INNER_OUTER_MISMATCH')
 hashes={x['hash'] for x in expected}
 need(ids(report['appliedHashes'],MAX_INPUTS) and set(report['appliedHashes'])==hashes,'APPLIED_SET_MISMATCH')
 need(ids(report['missing'],MAX_INPUTS),'CORE_REPORT_INVALID');need(not report['missing'],'DEPENDENCIES_MISSING')
 need(ids(report['heads'],MAX_INPUTS) and sorted(report['heads'])==request['expectedHeads'],'FRONTIER_MISMATCH')
 n=report['note'];need(type(n) is dict and set(n)=={'title','body','titleConflicts'},'CORE_REPORT_INVALID')
 need(type(n['title']) is str and type(n['body']) is str and type(n['titleConflicts']) is list and len(n['titleConflicts'])<=32 and all(type(x) is str for x in n['titleConflicts']),'CORE_REPORT_INVALID')
 try:
  need(len(n['title'].encode('utf-8'))<=1024 and all(len(x.encode('utf-8'))<=1024 for x in n['titleConflicts']) and len(canonical(n))<=MAX_NOTE_BYTES,'RESOURCE_LIMIT')
 except UnicodeError:raise ApplicationError('CORE_REPORT_INVALID') from None
 need(engine['kind']=='automerge' or allow_double,'CORE_NOT_REAL')
 return canonical(n)

class DocumentApplier:
 def __init__(self,owner,core,certificate,local_secret,*,app_id,space_id,document_id,epoch,schema_id,inbox=None,allow_contract_double=False,expected_pin=None,observer=None):
  need(isinstance(owner,ApplicationStore),'APPLICATION_STORE_REQUIRED')
  fixed(local_secret,32)
  for v in (space_id,document_id,schema_id):fixed(v,32)
  need(type(app_id) is str and 0<len(app_id)<=128 and type(epoch) is int and 1<=epoch<2**64 and type(allow_contract_double) is bool)
  need(type(certificate) is bytes and 0<len(certificate)<=4096)
  self.owner=owner;self._core=core;self._cert=certificate;self._scope={'app':app_id,'space':space_id.hex(),'document':document_id.hex(),'epoch':epoch,'schema':schema_id.hex()}
  self._scope_id=sha(canonical(self._scope));self._space=space_id;self._doc=document_id;self._schema=schema_id;self._epoch=epoch;self._inbox=inbox;self._allow=allow_contract_double
  self._key=hkdf_expand(hkdf_extract(hashed('document-apply-salt',[owner._storage.generation,self._scope_id]),local_secret),domain('document-apply-key',[self._scope_id]),32)
  self._key_context=hashed('document-apply-key-context',[owner._storage.generation,self._scope_id,self._key])
  self._seal=random_bytes(32);self._pid=os.getpid();self._thread=threading.get_ident();self._closed=False;self._busy=False;self._uncertain=False;self.observer=observer;self._known=None
  if inbox is not None:need(inbox.owner is owner and canonical(inbox._scope_data)==canonical(self._scope),'SCOPE_MISMATCH')
  self._audit()
  if expected_pin is not None:self._check_pin(expected_pin)
 def _enter(self,write=False):
  need(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER');need(not self._closed,'CLOSED');need(not self._busy,'REENTRANT_OPERATION');need(not self._uncertain,'APPLICATION_OUTCOME_UNKNOWN')
  self.owner._enter(write)
 def close(self):self._enter();self._closed=True;self._key=b'';self._seal=b''
 def _notify(self,name):
  if self.observer:self.observer(name)
 def _audit(self):
  self._enter();need(self.owner.audit()['valid'],'APPLICATION_CORRUPT')
  if self._known is not None:self._check_pin(self._known)
 def _auth(self):
  need(self._space not in self.owner._failed,'AUTH_PERSISTENCE_UNCERTAIN')
  row,state=self.owner._load(self._space)
  need(state.app_id==self._scope['app'],'SCOPE_MISMATCH');need(state.epoch==self._epoch,'EPOCH_CHANGED')
  need(row['phase']=='ACTIVE' and state._active is not None,'AUTHORITY_NOT_ACTIVE')
  state.authorize(self._cert,'read')
  return row,state
 def _engine(self):
  try:e=dict(self._core.identity)
  except Exception:raise ApplicationError('CORE_UNAVAILABLE') from None
  need(set(e)=={'name','version','kind','digest'} and e['name']=='@automerge/automerge' and e['version']=='3.4.1' and hex32(e['digest']),'CORE_IDENTITY_CHANGED')
  need(e['kind']=='automerge' or (self._allow and e['kind']=='contract-test-double'),'CORE_NOT_REAL')
  return e
 def _frontier(self):
  c=self.owner._storage.connection;r=c.execute('SELECT * FROM document_frontiers WHERE scope=?',(self._scope_id,)).fetchone()
  return dict(r) if r is not None else None
 def _external(self):
  """Exact encrypted bytes only; may run inside the owned transaction."""
  c=self.owner._storage.connection;pool={}
  for r in c.execute('''SELECT e.envelope_id,e.encrypted_bytes,a.certificate FROM envelopes e JOIN commit_ledger l ON l.commit_id=e.envelope_id JOIN auth_commits a USING(operation_id) WHERE e.space_id=? AND e.object_id=? AND e.epoch=?''',(self._space,self._doc,u64(self._epoch))):
   pool[bytes(r[0])]=(bytes(r[1]),bytes(r[2]))
  if self._inbox is not None:
   from .inbox import read_file
   need(read_file(self._inbox.root/'scope.json',4096)==self._inbox._meta_bytes,'INPUTS_CHANGED')
   for p in sorted((self._inbox.root/'records').iterdir()):
    raw=read_file(p,800000);o=decode(raw);need(type(o) is dict and set(o)=={0,1,2} and type(o[0]) is int and o[0]==1,'INPUTS_CHANGED')
    eid=objects.envelope_id(o[1]);need(p.name==eid.hex()+'.cbor','INPUTS_CHANGED')
    v=(o[1],o[2]);need(eid not in pool or pool[eid]==v,'INPUT_EQUIVOCATION');pool[eid]=v
  need(len(pool)<=256 and sum(len(x)+len(y) for x,y in pool.values())<=8*1024*1024,'RESOURCE_LIMIT')
  return pool
 @staticmethod
 def _pool_digest(pool):return sha(encode([[k,sha(encode(list(v)))] for k,v in sorted(pool.items())]))
 def _record(self,eid,raw,cert,state,current):
  try:
   o=decode(raw);h=decode(o[0]);need(objects.envelope_id(raw)==eid,'INPUTS_CHANGED')
   need((h[0],h[1],h[2],h[3])==(self._scope['app'],self._space,self._epoch,self._doc),'SCOPE_MISMATCH')
   node=state.control(h[13]);need(node.body[3]==self._epoch,'SCOPE_MISMATCH')
   members=state.membership_at(node.id);cb=member_certificate(state._p,state.app_id,members,cert)
   did=hashed('device-id',[state.app_id,cb[3]]);need(did==h[5] and members.get(did).role==2,'AUTHOR_NOT_AUTHORIZED')
   if current:plain=receive_change(state,raw,cert,expected_object=self._doc,expected_schema=self._schema).payload
   else:plain=objects.open_change(state._p,state._active.secret,cb[3],h,raw)
   return ChangeInput.create(h,plain,schema_id=self._schema)
  except SharedChangeError:raise
  except Exception:raise ApplicationError('INPUT_VERIFICATION_FAILED') from None
 def _collect(self,targets,state):
  external=self._external();pool=dict(external);c=self.owner._storage.connection;old=set()
  for r in c.execute('SELECT envelope_id,record FROM document_inputs WHERE scope=?',(self._scope_id,)):
   v=decode(r[1]);need(type(v) is dict and set(v)=={0,1},'APPLICATION_CORRUPT');value=(v[0],v[1]);eid=bytes(r[0])
   need(eid not in pool or pool[eid]==value,'INPUT_EQUIVOCATION');pool[eid]=value;old.add(eid)
  need(set(targets)-old,'NO_NEW_CHANGES')
  # Validate all available signed metadata before using its dependency identity.
  changes={};inners={};slots={}
  for eid,(raw,cert) in pool.items():
   ch=self._record(eid,raw,cert,state,False);h=ch.header;slot=(ch.actor,h[7])
   need(h[12] not in inners or inners[h[12]]==eid,'INPUT_EQUIVOCATION');need(slot not in slots or slots[slot]==eid,'ACTOR_EQUIVOCATION')
   inners[h[12]]=eid;slots[slot]=eid;changes[eid]=ch
  visiting=set();selected={};ordered=[]
  def visit(eid):
   need(eid in changes,'DEPENDENCIES_MISSING');need(eid not in visiting,'DEPENDENCY_CYCLE')
   if eid in selected:return
   need(len(visiting)+len(selected)<MAX_INPUTS,'RESOURCE_LIMIT');visiting.add(eid);ch=changes[eid]
   for cid in sorted(ch.header[10]):
    need(cid in inners,'DEPENDENCIES_MISSING');visit(inners[cid])
   visiting.remove(eid);selected[eid]=ch;ordered.append(eid)
  for eid in sorted(set(targets)|old):visit(eid)
  need(sum(len(x.payload) for x in selected.values())<=MAX_CLOSURE_BYTES,'RESOURCE_LIMIT')
  for eid in ordered:
   ch=selected[eid]
   if eid not in old:self._record(eid,*pool[eid],state,True)
   # Reuse the exact causal contract (including predecessor membership).
   closure=set()
   def ancestor(cid):
    if cid in closure:return
    closure.add(cid)
    for p in selected[inners[cid]].header[10]:ancestor(p)
   for cid in ch.header[10]:ancestor(cid)
   core_request(ch,tuple(Dependency(inners[cid],selected[inners[cid]]) for cid in sorted(closure)))
  hashes={ch.header[12].hex() for ch in selected.values()};deps={v.hex() for ch in selected.values() for v in ch.header[10]}
  request={'profile':PROFILE,'schema':'note-v1-local','changes':[selected[eid].descriptor() for eid in ordered],'expectedHeads':sorted(hashes-deps)}
  records=tuple((eid,ch.header[12],encode({0:pool[eid][0],1:pool[eid][1]})) for eid,ch in sorted(selected.items()))
  return request,records,self._pool_digest(external)
 def _intent(self,op,targets,expected):
  fixed(op,16);need(type(targets) is tuple and 1<=len(targets)<=MAX_INPUTS)
  for eid in targets:fixed(eid,32)
  need(len(set(targets))==len(targets) and type(expected) is int and 0<=expected<MAX_EVENTS)
  return sha(canonical({'profile':PROFILE,'scope':self._scope,'operationId':op.hex(),'targets':sorted(x.hex() for x in targets),'expectedRevision':expected}))
 def _decrypt(self,e):
  try:
   m,o=S.parse_record(e['record']);need(sha(e['record'])==e['record_digest'],'APPLICATION_CORRUPT')
   plain=self.owner._provider.open(self._key,o[1],o[0],o[2]);note=json.loads(plain)
   need(canonical(note)==plain and type(note) is dict,'MATERIALIZATION_INVALID')
   if not self._allow:need(m['evidenceClass']=='core-validated','SYNTHETIC_APPLICATION')
   return m,note
  except SharedChangeError:raise
  except Exception:raise ApplicationError('MATERIALIZATION_INVALID') from None
 def _history(self):
  c=self.owner._storage.connection
  return [(dict(r),*self._decrypt(dict(r))) for r in c.execute('SELECT * FROM document_apply_events WHERE scope=? ORDER BY revision',(self._scope_id,))]
 def _result(self,m,digest):
  verified=m['evidenceClass']=='core-validated'
  return {'profile':PROFILE,'operationId':m['operationId'],'revision':m['revision'],'heads':list(m['heads']),
          'inputIds':[x['envelopeId'] for x in m['inputs']],'eventDigest':digest.hex(),'candidatePersisted':True,
          'innerValidated':verified,'applied':verified,'replicated':False,'phase':'CORE_VALIDATED_LOCAL_APPLY' if verified else 'CANDIDATE_ONLY','productQualified':False}
 def inquire(self,op,targets,*,expected_revision):
  self._audit();req=self._intent(op,targets,expected_revision)
  e=self.owner._storage.connection.execute('SELECT * FROM document_apply_events WHERE operation_id=?',(op,)).fetchone()
  if e is None:return None
  need(e['scope']==self._scope_id and e['request_digest']==req,'OPERATION_CONFLICT');m,_=self._decrypt(dict(e))
  self._remember();return self._result(m,e['record_digest'])
 def prepare(self,op,targets,*,expected_revision):
  self._audit();self.owner._enter(True);req=self._intent(op,targets,expected_revision);engine=self._engine()
  need(self.owner._storage.connection.execute('SELECT 1 FROM document_apply_events WHERE operation_id=?',(op,)).fetchone() is None,'OPERATION_ALREADY_COMMITTED')
  history=self._history();f=self._frontier();need(expected_revision==(f['revision'] if f else 0),'STALE_FRONTIER')
  mode='core-validated' if engine['kind']=='automerge' else 'candidate'
  if history:need(history[-1][1]['evidenceClass']==mode,'APPLICATION_MODE_MISMATCH')
  row,state=self._auth();before=row['row_digest'];fence=self.owner._storage.fencing_token;self._busy=True
  try:
   request,records,source=self._collect(targets,state)
   try:report=self._core.materialize(request)
   except SharedChangeError:raise
   except Exception:raise ApplicationError('CORE_FAILURE') from None
   need(canonical(engine)==canonical(self._engine()),'CORE_IDENTITY_CHANGED')
   note=check_materialization(request,report,engine,self._allow)
   need(self._auth()[0]['row_digest']==before,'OWNER_STATE_CHANGED');need(self._pool_digest(self._external())==source,'INPUTS_CHANGED')
   c=self.owner._storage.connection
   need(c.execute('SELECT count(*) FROM document_apply_events').fetchone()[0]<MAX_EVENTS and c.execute('SELECT count(*) FROM document_apply_nonces').fetchone()[0]<MAX_NONCES,'RESOURCE_LIMIT')
   used=sum(c.execute('SELECT COALESCE(sum(length(record)),0) FROM '+t).fetchone()[0] for t in ('document_inputs','document_apply_events'))
   need(used+sum(len(r[2]) for r in records)+len(note)+128*1024<=MAX_RECORD_BYTES,'RESOURCE_LIMIT')
   nr=random_bytes(16);nonce=random_bytes(24);attempted=False
   try:
    c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO document_apply_nonces VALUES(?,?,?,?,?,NULL)',(nr,self._scope_id,self._key_context,nonce,req))
    self._notify('apply.nonce_before_commit');attempted=True;c.execute('COMMIT');self._notify('apply.nonce_after_commit')
   except BaseException as exc:
    if c.in_transaction:c.execute('ROLLBACK')
    if attempted:self._uncertain=True;raise ApplicationError('APPLICATION_OUTCOME_UNKNOWN') from None
    if isinstance(exc,sqlite3.Error):raise sqlite_error(exc) from None
    raise
   m={'profile':PROFILE,'storeGeneration':self.owner._storage.generation.hex(),'scope':dict(self._scope),'scopeDigest':self._scope_id.hex(),
      'operationId':op.hex(),'requestDigest':req.hex(),'expectedRevision':expected_revision,'revision':expected_revision+1,
      'previousDigest':f['record_digest'].hex() if f else '0'*64,'engine':engine,'evidenceClass':mode,
      'inputs':[{'envelopeId':eid.hex(),'innerId':cid.hex(),'digest':sha(raw).hex()} for eid,cid,raw in records],
      'heads':request['expectedHeads'],'authority':{'rowDigest':before.hex(),'head':row['head'].hex(),'epoch':self._epoch,'revision':row['revision'].hex()},
      'certificateDigest':sha(self._cert).hex(),'reservationId':nr.hex(),'keyContext':self._key_context.hex(),'coreRequestDigest':request_digest(request),'targets':sorted(x.hex() for x in targets)}
   metadata=canonical(m);ciphertext=self.owner._provider.seal(self._key,nonce,metadata,note);self._notify('apply.after_encrypt')
   p=PreparedApplication(op,tuple(sorted(targets)),expected_revision,metadata,ciphertext,nonce,records,before,source,fence,self,b'')
   return PreparedApplication(**dict(p.__dict__,_seal=self._tag(p)))
  finally:self._busy=False
 def _tag(self,p):
  return hmac.digest(self._seal,encode([p.operation_id,list(p.targets),p.expected_revision,p.metadata,p.ciphertext,p.nonce,[[a,b,sha(c)] for a,b,c in p.records],p.authority_digest,p.source_digest,p.writer_fence]),'sha256')
 def _guard(self,p):
  storage=self.owner._storage
  fence=storage.connection.execute('SELECT fencing_token FROM writer_fences WHERE store_generation=?',(storage.generation,)).fetchone()
  need(fence is not None and fence[0]==p.writer_fence and storage.fencing_token==p.writer_fence,'WRITER_FENCE_CHANGED')
  need(self._auth()[0]['row_digest']==p.authority_digest,'OWNER_STATE_CHANGED');need(self._pool_digest(self._external())==p.source_digest,'INPUTS_CHANGED');self.owner._storage._settings()
 def commit(self,p):
  self._audit();self.owner._enter(True);need(type(p) is PreparedApplication and p._owner is self,'FOREIGN_PREPARED_APPLY')
  need(hmac.compare_digest(p._seal,self._tag(p)),'PREPARED_CHANGED');m=json.loads(p.metadata)
  need(canonical(m['engine'])==canonical(self._engine()),'CORE_IDENTITY_CHANGED')
  old=self.inquire(p.operation_id,p.targets,expected_revision=p.expected_revision)
  if old is not None:return old
  self._guard(p);c=self.owner._storage.connection;f=self._frontier();need((f['revision'] if f else 0)==p.expected_revision,'STALE_FRONTIER')
  record=encode({0:p.metadata,1:p.nonce,2:p.ciphertext});record_digest=sha(record);attempted=False;self._busy=True;self.owner._busy=True
  try:
   self._notify('apply.before_begin');c.execute('BEGIN IMMEDIATE');self._notify('apply.after_begin');self._guard(p)
   f=self._frontier();need((f['revision'] if f else 0)==p.expected_revision,'STALE_FRONTIER')
   need((f['record_digest'].hex() if f else '0'*64)==m['previousDigest'],'STALE_FRONTIER')
   for eid,cid,raw in p.records:
    oldrow=c.execute('SELECT * FROM document_inputs WHERE scope=? AND envelope_id=?',(self._scope_id,eid)).fetchone()
    if oldrow is None:c.execute('INSERT INTO document_inputs VALUES(?,?,?,?,?,?,?)',(self._scope_id,eid,cid,raw,sha(raw),p.operation_id,m['evidenceClass']))
    else:need(oldrow['inner_id']==cid and oldrow['record']==raw and oldrow['record_digest']==sha(raw),'APPLICATION_CORRUPT')
   self._notify('apply.after_inputs')
   c.execute('INSERT INTO document_apply_events VALUES(?,?,?,?,?,?,?)',(p.operation_id,self._scope_id,m['revision'],bytes.fromhex(m['requestDigest']),bytes.fromhex(m['previousDigest']),record,record_digest));self._notify('apply.after_event')
   c.execute('INSERT OR REPLACE INTO document_frontiers VALUES(?,?,?,?,?,?)',(self._scope_id,m['revision'],p.operation_id,record_digest,canonical(m['heads']),m['evidenceClass']));self._notify('apply.after_frontier')
   n=c.execute('UPDATE document_apply_nonces SET used_by=? WHERE reservation_id=? AND scope=? AND nonce=? AND request_digest=? AND used_by IS NULL',(p.operation_id,bytes.fromhex(m['reservationId']),self._scope_id,p.nonce,bytes.fromhex(m['requestDigest']))).rowcount
   need(n==1,'NONCE_RESERVATION_INVALID');self._notify('apply.after_nonce_link');self._notify('apply.before_commit');self._guard(p)
   need(canonical(m['engine'])==canonical(self._engine()),'CORE_IDENTITY_CHANGED')
   need(not S.audit_records(c,self.owner._storage.generation),'APPLICATION_CORRUPT')
   # Exact bytes bind any cooperative fault injected after row insertion.
   actual=c.execute('SELECT record FROM document_apply_events WHERE operation_id=?',(p.operation_id,)).fetchone();need(actual is not None and actual[0]==record,'APPLICATION_CORRUPT')
   attempted=True;c.execute('COMMIT');self._notify('apply.after_commit')
  except BaseException as exc:
   failed=False
   if c.in_transaction:
    try:c.execute('ROLLBACK')
    except sqlite3.Error:failed=True
   if attempted or failed:self._uncertain=True;raise ApplicationError('APPLICATION_OUTCOME_UNKNOWN') from None
   if isinstance(exc,(SharedChangeError,StoreError)):raise
   if isinstance(exc,sqlite3.Error):raise sqlite_error(exc) from None
   if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
   raise ApplicationError('APPLICATION_ABORTED') from None
  finally:self.owner._busy=False;self._busy=False
  self._remember();return self._result(m,record_digest)
 def apply(self,op,targets,*,expected_revision):
  old=self.inquire(op,targets,expected_revision=expected_revision)
  if old is not None:return old
  return self.commit(self.prepare(op,targets,expected_revision=expected_revision))
 def _db_stamp(self):
  c=self.owner._storage.connection
  return (c.total_changes,c.execute('PRAGMA data_version').fetchone()[0],c.execute('PRAGMA schema_version').fetchone()[0])
 def read(self):
  self._audit();before=self._auth()[0]['row_digest'];frontier=self._pin_raw();stamp=self._db_stamp();self._busy=True
  try:
   history=self._history()
   need(self._auth()[0]['row_digest']==before,'OWNER_STATE_CHANGED')
   need(self._db_stamp()==stamp and self._pin_raw()==frontier,'APPLICATION_CHANGED')
  finally:self._busy=False
  self._remember()
  if not history:return {'profile':PROFILE,'revision':0,'heads':[],'phase':'EMPTY','note':None,'innerValidated':False,'applied':False,'writable':False}
  e,m,n=history[-1]
  return dict(self._result(m,e['record_digest']),note=n,writable=False,freshness='KNOWN_AUTHORITY_ONLY')
 def pin(self):
  self._audit();return self._pin_raw()
 def _pin_raw(self):
  f=self._frontier()
  return {'profile':PROFILE,'storeGeneration':self.owner._storage.generation.hex(),'scopeDigest':self._scope_id.hex(),'revision':f['revision'] if f else 0,'eventDigest':f['record_digest'].hex() if f else '0'*64}
 def _remember(self):self._known=self._pin_raw()
 def _check_pin(self,pin):
  try:
   need(type(pin) is dict and set(pin)=={'profile','storeGeneration','scopeDigest','revision','eventDigest'} and type(pin['revision']) is int and 0<=pin['revision']<=MAX_EVENTS,'APPLICATION_PIN_MISMATCH')
   now=self._pin_raw();need(all(now[k]==pin[k] for k in ('profile','storeGeneration','scopeDigest')) and now['revision']>=pin['revision'],'APPLICATION_PIN_MISMATCH')
   if pin['revision']:
    r=self.owner._storage.connection.execute('SELECT record_digest FROM document_apply_events WHERE scope=? AND revision=?',(self._scope_id,pin['revision'])).fetchone()
    need(r is not None and r[0].hex()==pin['eventDigest'],'APPLICATION_PIN_MISMATCH')
   else:need(pin['eventDigest']=='0'*64,'APPLICATION_PIN_MISMATCH')
  except (ValueError,TypeError,KeyError):raise ApplicationError('APPLICATION_PIN_MISMATCH') from None
