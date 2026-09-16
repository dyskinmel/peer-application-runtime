"""Bounded, durable *pending* encrypted synchronization inbox (local candidate).

No CRDT, network fetch, Store commit, semantic ACK, eviction or auto replay.
The caller owns the authoritative Store and supplies its current known history.
Records are immutable envelopes/certificates; readiness and permissions are
re-derived. This is not protection against arbitrary same-UID code or rollback.
"""
from __future__ import annotations
import hashlib, json, os, stat, threading, tempfile
from pathlib import Path
from par_store.fs import safe, sync_dir, WriterLock
from par_store.errors import StoreError
from par_wire.codec import encode, decode
from par_crypto import objects
from par_crypto.primitives import domain, hashed
from par_auth.membership import member_certificate
from par_auth.receiver import receive_change
from par_auth.errors import AuthError
from par_store.model import u64
from .contracts import (ChangeInput, Dependency, SharedChangeError, core_request,
                        check_report, canonical, MAX_CHANGE)
from .dependencies import stamp

PROFILE = 'par-sync-inbox-local-0033'
RECORD_MAX = 800 * 1024
DEFAULT_BYTES = 8 * 1024 * 1024
DEFAULT_RECORDS = 64

class InboxError(Exception):
    def __init__(self, code): self.code=code; super().__init__(code)

def need(ok, code='INVALID_INPUT'):
    if not ok: raise InboxError(code)

def fixed(value, n): need(type(value) is bytes and len(value)==n)

def private_dir(path):
    safe(path); s=path.stat()
    need(stat.S_ISDIR(s.st_mode) and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o700,'UNSAFE_PATH')

def read_file(path, limit):
    safe(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o600,'UNSAFE_PATH')
        need(0<before.st_size<=limit,'INBOX_CORRUPT')
        raw=f.read(before.st_size+1); after=os.fstat(f.fileno()); visible=path.stat()
        signature=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_nlink)
        need(signature(before)==signature(after)==signature(visible) and len(raw)==before.st_size,'INBOX_CORRUPT')
        return raw

class SyncInbox:
    """One app/space/document/epoch, one cooperative PID/thread, exclusive flock.

    `receive` acknowledges inbox bytes, not the application Store. All current
    authority/epoch checks run again before dependencies are exposed to a core.
    """
    @classmethod
    def create(cls, root, owner, *, app_id, space_id, document_id, epoch, schema_id,
               max_records=DEFAULT_RECORDS, max_bytes=DEFAULT_BYTES, observer=None):
        scope=cls._scope(app_id,space_id,document_id,epoch,schema_id)
        need(type(max_records) is int and 1<=max_records<=DEFAULT_RECORDS)
        need(type(max_bytes) is int and 1<=max_bytes<=DEFAULT_BYTES)
        root=safe(Path(root)); need(not root.exists(),'INBOX_EXISTS')
        root.mkdir(mode=0o700); (root/'records').mkdir(mode=0o700); (root/'staging').mkdir(mode=0o700)
        metadata={'profile':PROFILE,'scope':scope,'generation':os.urandom(16).hex(),
                  'maxRecords':max_records,'maxBytes':max_bytes}
        with open(root/'scope.json','xb') as f:
            os.fchmod(f.fileno(),0o600); f.write(canonical(metadata));f.flush();os.fsync(f.fileno())
        sync_dir(root/'records');sync_dir(root/'staging');sync_dir(root);sync_dir(root.parent)
        return cls.open(root,owner,app_id=app_id,space_id=space_id,document_id=document_id,
                        epoch=epoch,schema_id=schema_id,observer=observer)
    @staticmethod
    def _scope(app,space,doc,epoch,schema):
        need(type(app) is str and 0<len(app)<=128)
        for v in (space,doc,schema):fixed(v,32)
        need(type(epoch) is int and 1<=epoch<2**64)
        return {'app':app,'space':space.hex(),'document':doc.hex(),'epoch':epoch,'schema':schema.hex()}
    @classmethod
    def open(cls,root,owner,*,app_id,space_id,document_id,epoch,schema_id,expected_pin=None,observer=None):
        scope=cls._scope(app_id,space_id,document_id,epoch,schema_id)
        root=safe(Path(root));lock=None
        try:
            for p in (root,root/'records',root/'staging'):private_dir(p)
            try:lock=WriterLock(root)
            except StoreError as e:
                raise InboxError('INBOX_BUSY' if e.code=='WRITER_BUSY' else 'UNSAFE_PATH') from None
            raw=read_file(root/'scope.json',4096);m=json.loads(raw)
            need(type(m) is dict and set(m)=={'profile','scope','generation','maxRecords','maxBytes'},'INBOX_CORRUPT')
            need(canonical(m)==raw and m['profile']==PROFILE,'INBOX_CORRUPT')
            need(canonical(m['scope'])==canonical(scope),'SCOPE_MISMATCH')
            need(type(m['generation']) is str and len(m['generation'])==32 and bytes.fromhex(m['generation']).hex()==m['generation'],'INBOX_CORRUPT')
            need(type(m['maxRecords']) is int and 1<=m['maxRecords']<=DEFAULT_RECORDS,'INBOX_CORRUPT')
            need(type(m['maxBytes']) is int and 1<=m['maxBytes']<=DEFAULT_BYTES,'INBOX_CORRUPT')
            self=cls();self.root=root;self.owner=owner;self._scope_data=scope;self._metadata=m;self._meta_bytes=raw
            self._space=space_id;self._doc=document_id;self._schema=schema_id;self._epoch=epoch
            self._pid=os.getpid();self._thread=threading.get_ident();self._lock=lock;self._closed=False;self._busy=False;self._uncertain=False
            self._seen={};self.observer=observer;self._records()
            if expected_pin is not None:self._check_pin(expected_pin)
            return self
        except BaseException:
            if lock:lock.close()
            raise
    def _enter(self):
        need(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER')
        need(not self._closed,'CLOSED');need(not self._busy,'REENTRANT_OPERATION');need(not self._uncertain,'INBOX_OUTCOME_UNKNOWN')
        self.owner._enter()
    def close(self):
        need(os.getpid()==self._pid and threading.get_ident()==self._thread,'WRONG_OWNER')
        need(not self._busy,'REENTRANT_OPERATION')
        if not self._closed:self._lock.close();self._closed=True
    def _notify(self,stage):
        if self.observer:self.observer(stage)
    def _disk(self):
        for p in (self.root,self.root/'records',self.root/'staging'):private_dir(p)
        need(set(p.name for p in self.root.iterdir())=={'records','staging','scope.json','.store.lock'},'INBOX_CORRUPT')
        need(read_file(self.root/'scope.json',4096)==self._meta_bytes,'INBOX_CORRUPT')
        # Orphans are explicitly bounded and retained, never interpreted as committed.
        leftovers=list((self.root/'staging').iterdir())
        need(len(leftovers)<=DEFAULT_RECORDS,'RESOURCE_BLOCKED')
        size=0
        for p in leftovers:
            need(p.name.startswith('receive-') and p.name.endswith('.part'),'INBOX_CORRUPT')
            safe(p);s=p.stat();need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600,'UNSAFE_PATH')
            need(s.st_size<=RECORD_MAX,'INBOX_CORRUPT');size+=s.st_size
        need(size<=DEFAULT_BYTES,'RESOURCE_BLOCKED')
    def _outer(self,raw,certificate,state):
        need(type(raw) is bytes and 0<len(raw)<=RECORD_MAX and type(certificate) is bytes and 0<len(certificate)<=4096)
        try:
            out=decode(raw);need(type(out) is dict and set(out)=={0,1,2,3},'AUTH_REJECTED')
            head=decode(out[0]);objects.change_header(head)
            need((head[0],head[1],head[2],head[3],head[9])==
                 (self._scope_data['app'],self._space,self._epoch,self._doc,self._schema),'SCOPE_MISMATCH')
            for k in (2,4,7,11,14,15):need(type(head[k]) is int,'AUTH_REJECTED')
            need(head[4]==1 and head[14]==1 and 0<head[11]<=MAX_CHANGE,'AUTH_REJECTED')
            c=state.control(head[13]);need(c.body[3]==head[2],'AUTH_REJECTED')
            members=state.membership_at(c.id);cert=member_certificate(state._p,state.app_id,members,certificate)
            did=hashed('device-id',[state.app_id,cert[3]])
            need(did==head[5] and members.get(did).role==2,'AUTH_REJECTED')
            state._p.verify(cert[3],domain('envelope-sign',[out[0],out[1],out[2]]),out[3])
            return head
        except InboxError:raise
        except Exception:raise InboxError('AUTH_REJECTED') from None
    def _records(self):
        self._enter();self._disk();_,state=self.owner._load(self._space);result={};digests={};total=0
        names=list((self.root/'records').iterdir());need(len(names)<=self._metadata['maxRecords']+1,'INBOX_CORRUPT')
        for p in sorted(names):
            try:
                need(len(p.name)==69 and p.name.endswith('.cbor') and bytes.fromhex(p.stem).hex()==p.stem,'INBOX_CORRUPT')
                data=read_file(p,RECORD_MAX);rec=decode(data)
                need(type(rec) is dict and set(rec)=={0,1,2} and type(rec[0]) is int and rec[0]==1,'INBOX_CORRUPT')
                need(objects.envelope_id(rec[1]).hex()==p.stem,'INBOX_CORRUPT')
                h=self._outer(rec[1],rec[2],state);total+=len(data)
                result[bytes.fromhex(p.stem)]=(rec[1],rec[2],h);digests[p.stem]=hashlib.sha256(data).hexdigest()
            except Exception as e:
                if isinstance(e,InboxError) and e.code=='UNSAFE_PATH':raise
                raise InboxError('INBOX_CORRUPT') from None
        need(total<=self._metadata['maxBytes']+RECORD_MAX,'INBOX_CORRUPT')
        need(all(digests.get(k)==v for k,v in self._seen.items()),'PIN_MISMATCH')
        self._seen=digests
        return result,state,total
    @staticmethod
    def _slot(h):return (h[5],h[6],h[7])
    def _conflict(self,records):
        slots={};inner={}
        for eid,(_,_,h) in records.items():
            slot=self._slot(h)
            if slot in slots and slots[slot]!=eid:return True
            if h[12] in inner and inner[h[12]]!=eid:return True
            slots[slot]=eid;inner[h[12]]=eid
        return False
    def _store_conflict(self,records,state):
        need(self.owner.audit()['valid'],'STORE_VERIFICATION_FAILED')
        c=self.owner._storage.connection
        # Compare signed headers with the local Store as well as the inbox.
        # Bounded inbox slots; only rows matching these candidate author slots
        # or inner IDs are selected. The Store audit validates all source rows.
        for eid,(_,_,h) in records.items():
            for row in c.execute("SELECT e.envelope_id,e.encrypted_bytes,a.certificate FROM envelopes e JOIN commit_ledger l ON l.commit_id=e.envelope_id JOIN auth_commits a USING(operation_id) WHERE e.space_id=? AND e.object_id=? AND e.epoch=?",(self._space,self._doc,u64(self._epoch))):
                if row[0]==eid:continue
                oh=decode(decode(row[1])[0])
                if self._slot(oh)==self._slot(h) or oh[12]==h[12]:
                    self._outer(row[1],row[2],state);return True
        return False
    def _check_unchanged_bytes(self,expected):
        self._disk();actual={}
        for p in (self.root/'records').iterdir():
            actual[p.stem]=hashlib.sha256(read_file(p,RECORD_MAX)).hexdigest()
        need(actual==expected,'INBOX_CORRUPT')
    def _current(self,raw,cert,state):
        current=self.owner.status(self._space)['state']
        if current=='AUTH_PERSISTENCE_UNCERTAIN':raise AuthError(current)
        got=receive_change(state,raw,cert,expected_object=self._doc,expected_schema=self._schema)
        return ChangeInput.create(decode(decode(raw)[0]),got.payload,schema_id=self._schema)
    def receive(self,raw,certificate):
        records,state,total=self._records();before=stamp(self.owner,self._space)
        self._outer(raw,certificate,state)
        try:self._current(raw,certificate,state)
        except Exception:raise InboxError('AUTH_REJECTED') from None
        eid=objects.envelope_id(raw);record=encode({0:1,1:raw,2:certificate});need(len(record)<=RECORD_MAX,'RESOURCE_BLOCKED')
        if eid in records:
            need(records[eid][:2]==(raw,certificate),'RECORD_EQUIVOCATION')
            # Idempotent retry after a process stopped at publication: re-sync bytes/dir.
            fd=os.open(self.root/'records'/(eid.hex()+'.cbor'),os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
            sync_dir(self.root/'records')
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            return self._receipt(eid)
        h=decode(decode(raw)[0]);conflict=any(self._slot(x[2])==self._slot(h) or x[2][12]==h[12] for x in records.values()) or self._store_conflict({eid:(raw,certificate,h)},state)
        # Reserve one extra bounded evidence slot; never an unbounded exception.
        slots=self._metadata['maxRecords']+(1 if conflict else 0)
        budget=self._metadata['maxBytes']+(RECORD_MAX if conflict else 0)
        need(len(records)<slots and total+len(record)<=budget,'RESOURCE_BLOCKED')
        dest=self.root/'records'/(eid.hex()+'.cbor');temp=None;published=False;self._busy=True
        try:
            self._notify('inbox.before_write')
            fd,name=tempfile.mkstemp(prefix='receive-',suffix='.part',dir=self.root/'staging');temp=Path(name)
            with os.fdopen(fd,'wb') as f:
                f.write(record);f.flush();self._notify('inbox.after_write');os.fsync(f.fileno());self._notify('inbox.after_file_sync')
            self._notify('inbox.before_publish')
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            # Lifetime writer lock; destination never overwritten. Rename removes the
            # staging pathname atomically; only this cooperative writer publishes.
            need(not dest.exists(),'RECORD_EQUIVOCATION')
            os.rename(temp,dest);published=True;self._notify('inbox.after_publish')
            sync_dir(dest.parent);sync_dir(self.root/'staging');self._notify('inbox.after_dirsync')
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            self._notify('inbox.before_receipt')
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            self._seen[eid.hex()]=hashlib.sha256(record).hexdigest()
            return self._receipt(eid)
        except BaseException as e:
            if published:
                self._uncertain=True;raise InboxError('INBOX_OUTCOME_UNKNOWN') from None
            if isinstance(e,InboxError):raise
            if isinstance(e,(KeyboardInterrupt,SystemExit)):raise
            raise InboxError('INBOX_WRITE_FAILED') from None
        finally:
            self._busy=False
            if temp is not None and temp.exists():
                try:temp.unlink();sync_dir(self.root/'staging')
                except OSError:pass  # bounded orphans; not a committed record
    def _receipt(self,eid):
        return {'profile':PROFILE,'envelopeId':eid.hex(),'state':'PENDING_BYTES','inboxStored':True,
                'localCommitted':False,'innerValidated':False,'applied':False,'replicated':False}
    def pin(self):
        self._records()
        return {'profile':PROFILE,'generation':self._metadata['generation'],
                'scope':dict(self._scope_data),'records':dict(sorted(self._seen.items()))}
    def _check_pin(self,pin):
        try:
            need(type(pin) is dict and set(pin)=={'profile','generation','scope','records'},'PIN_MISMATCH')
            now=self.pin();need(type(pin['records']) is dict,'PIN_MISMATCH')
            need(canonical({k:pin[k] for k in ('profile','generation','scope')})==canonical({k:now[k] for k in ('profile','generation','scope')}),'PIN_MISMATCH')
            need(all(type(k) is str and type(v) is str and now['records'].get(k)==v for k,v in pin['records'].items()),'PIN_MISMATCH')
        except (TypeError,ValueError,KeyError):raise InboxError('PIN_MISMATCH') from None
    def usage(self):
        records,_,n=self._records()
        return {'records':len(records),'recordBytes':n,'maxRecords':self._metadata['maxRecords'],
                'maxBytes':self._metadata['maxBytes'],'evidenceReserveRecords':1,
                'physicalQuotaGuaranteed':False,'automaticEviction':False}
    def _view(self,eid,state,**extras):
        return dict(self._receipt(eid),state=state,missing=[],missingPrevious=[],**extras)
    def _evaluation(self,eid):
        fixed(eid,32);records,state,_=self._records();before=stamp(self.owner,self._space)
        if eid not in records:return self._view(eid,'NOT_OBSERVED',inboxStored=False),None,before
        if self._conflict(records) or self._store_conflict(records,state):return self._view(eid,'QUARANTINED',reason='SIGNED_EQUIVOCATION'),None,before
        row=records[eid]
        try:change=self._current(*row[:2],state)
        except AuthError as e:
            phase='REBASE_REQUIRED' if e.code=='REBASE_REQUIRED' else 'WAITING_AUTHORITY'
            return self._view(eid,phase,reason=e.code),None,before
        except SharedChangeError as e:return self._view(eid,'INVALID_DEPENDENCY_GRAPH',reason=e.code),None,before
        c=self.owner._storage.connection
        need(self.owner.audit()['valid'],'STORE_VERIFICATION_FAILED')
        nodes={};visiting=set();missing=set();missing_prev=set();ordered=[]
        def lookup(cid):
            found=[(x,*r[:2]) for x,r in records.items() if r[2][12]==cid]
            found+=list(c.execute('''SELECT e.envelope_id,e.encrypted_bytes,a.certificate FROM envelopes e
                JOIN commit_ledger l ON l.commit_id=e.envelope_id JOIN auth_commits a USING(operation_id)
                WHERE e.space_id=? AND e.object_id=? AND e.epoch=? AND e.change_hash=? LIMIT 2''',
                (self._space,self._doc,u64(self._epoch),cid)))
            unique={}
            for x,r,cert in found:
                if x in unique and unique[x]!=(r,cert):raise SharedChangeError('DEPENDENCY_EQUIVOCATION')
                unique[x]=(r,cert)
            if len(unique)>1:raise SharedChangeError('DEPENDENCY_EQUIVOCATION')
            if not unique:return None
            dep_id,(raw,cert)=next(iter(unique.items()));self._outer(raw,cert,state)
            # Historical signed dependencies from local Store may be by an editor
            # removed later; don't grant them new writing authority. Same epoch only.
            header=decode(decode(raw)[0]);members=state.membership_at(header[13]);cert_body=member_certificate(state._p,state.app_id,members,cert)
            plain=objects.open_change(state._p,state._active.secret,cert_body[3],header,raw)
            return Dependency(dep_id,ChangeInput.create(header,plain,schema_id=self._schema))
        def visit(cid):
            if cid in visiting:raise SharedChangeError('DEPENDENCY_CYCLE')
            if cid in nodes:return
            if len(nodes)+len(visiting)>=128:raise SharedChangeError('RESOURCE_LIMIT')
            dep=lookup(cid)
            if dep is None:missing.add(cid);return
            visiting.add(cid)
            for parent in sorted(dep.change.header[10]):visit(parent)
            visiting.remove(cid);nodes[cid]=dep;ordered.append(dep)
        try:
            for cid in sorted(change.header[10]):visit(cid)
            if change.header[8] is not None and not any(d.envelope_id==change.header[8] for d in ordered):
                # Only request unknown predecessor; known-but-noncausal is invalid.
                exists=change.header[8] in records or c.execute('SELECT 1 FROM envelopes WHERE envelope_id=?',(change.header[8],)).fetchone()
                if not exists:missing_prev.add(change.header[8])
            if missing or missing_prev:
                view=self._view(eid,'WAITING_DEPENDENCIES');view['missing']=sorted(x.hex() for x in missing);view['missingPrevious']=sorted(x.hex() for x in missing_prev)
                need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED');return view,None,before
            request=core_request(change,tuple(ordered))
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            return self._view(eid,'READY_FOR_CORE'),request,before
        except SharedChangeError as e:
            status='RESOURCE_BLOCKED' if e.code=='RESOURCE_LIMIT' else ('QUARANTINED' if e.code=='DEPENDENCY_EQUIVOCATION' else 'INVALID_DEPENDENCY_GRAPH')
            return self._view(eid,status,reason=e.code),None,before
    def inspect(self,eid):return self._evaluation(eid)[0]
    def needed(self,*,limit=16):
        need(type(limit) is int and 1<=limit<=128)
        records,_,_=self._records();missing=set()
        for eid in records:missing.update(self.inspect(eid)['missing'])
        return sorted(missing)[:limit]
    def validate(self,eid,core=None,*,allow_contract_double=False):
        need(type(allow_contract_double) is bool);view,request,before=self._evaluation(eid)
        if request is None:return view
        if core is None:return self._view(eid,'CORE_BLOCKED',reason='CORE_UNAVAILABLE')
        try:
            identity=dict(core.identity)
            if identity.get('kind')!='automerge' and not (allow_contract_double and identity.get('kind')=='contract-test-double'):
                return self._view(eid,'CORE_BLOCKED',reason='CORE_NOT_REAL')
            expected_bytes=dict(self._seen)
            self._busy=True
            try:report=core.validate(request)
            except (SharedChangeError,InboxError):raise
            except Exception:raise SharedChangeError('CORE_FAILURE') from None
            if identity!=core.identity:raise SharedChangeError('CORE_IDENTITY_CHANGED')
            checked=check_report(request,report,expected_engine=identity,allow_contract_double=allow_contract_double)
            need(before==stamp(self.owner,self._space),'OWNER_STATE_CHANGED')
            self._check_unchanged_bytes(expected_bytes)
            # Scratch validation only; no application Store update or durable core ACK.
            result=self._view(eid,'SEMANTICALLY_VALIDATED_PENDING' if checked.semantic_validated else 'CONTRACT_CHECKED')
            result.update(innerValidated=checked.semantic_validated,coreDigest=identity['digest'],requestDigest=checked.request_hash)
            return result
        except SharedChangeError as e:
            status='CORE_BLOCKED' if e.code in ('CORE_UNAVAILABLE','CORE_TIMEOUT','CORE_IDENTITY_CHANGED','CORE_RUNTIME_CHANGED','CORE_NOT_REAL','CORE_FAILURE') else 'CORE_REJECTED'
            return self._view(eid,status,reason=e.code)
        finally:self._busy=False
