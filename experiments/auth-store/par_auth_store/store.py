"""Durable known-history authority + compare-before-commit, in one SQLite DB.

Candidate adapter for cooperative local writers. No latest-head oracle, secure
key vault, rollback-resistant hardware or Automerge application is supplied.
"""
from __future__ import annotations
import hmac, sqlite3, threading
from dataclasses import replace
from pathlib import Path
from par_wire.codec import encode, decode
from par_store.store import Store, sqlite_error
from par_store.model import u64, from_u64, fixed
from par_store.errors import StoreError
from par_auth.chain import AuthorityState
from par_auth.errors import AuthError
from par_auth.replay import export_public_replay, restore_public_replay
from par_auth.membership import member_certificate
from par_crypto.primitives import hashed, random_bytes
from par_crypto import objects
from .backend import BoundStorage
from .errors import AuthorityStoreError as E
from .model import BoundWrite, ROW_FIELDS, STATE_MAP, row_hash, proof_hash, pack_material, unpack_material, sha
from . import schema

TERMINAL={'CONTROL_FORK','CONTENT_MEMBERSHIP_CHANGED','NO_CONTENT_RECIPIENT'}

class AuthorityStore:
    def __init__(self,storage,provider):
        self._storage=storage;self._provider=provider;self._thread=threading.get_ident()
        self._cache={};self._failed={};self._pending=None;self._busy=False;self._seal_key=random_bytes(32)
        storage.authority=self
    @classmethod
    def create(cls,root,*,provider,allow_unpatched_sqlite=False):
        return cls(BoundStorage.create(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite),provider)
    @classmethod
    def open(cls,root,*,provider,allow_unpatched_sqlite=False,expected_pins=()):
        storage=BoundStorage.open(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite)
        self=cls(storage,provider)
        try:
            if not self.audit()['valid']:raise E('AUTH_STORE_CORRUPT')
            self._check_pins(expected_pins)
            # Never trust persisted active flags without opening/verifying materials again.
            if not storage.restore_read_only:
                for r in list(storage.connection.execute("SELECT space_id FROM auth_spaces WHERE phase='ACTIVE'")):
                    row,st=self._load(r[0]);self._persist(row,st,None)
            return self
        except BaseException:self.close();raise
    def close(self):
        self._cache.clear();self._pending=None;self._storage.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    @property
    def observer(self):return self._storage.observer
    @observer.setter
    def observer(self,v):self._storage.observer=v
    def _enter(self,write=False):
        self._storage._alive()
        if threading.get_ident()!=self._thread:raise E('WRONG_THREAD')
        if self._busy or self._storage._busy or self._storage.connection.in_transaction:raise E('REENTRANT_OPERATION')
        if write:self._storage._writable()
    def _row(self,space):
        fixed(space,32);c=self._storage.connection
        r=c.execute('SELECT * FROM auth_spaces WHERE space_id=?',(space,)).fetchone()
        if r is None:raise E('AUTH_SPACE_MISSING')
        row=dict(r)
        try:
            if row_hash(row)!=row['row_digest'] or hashed('auth-local/replay',[row['replay']])!=row['replay_digest']:raise ValueError()
            sp=c.execute('SELECT * FROM spaces WHERE space_id=?',(space,)).fetchone()
            if sp is None or (sp['app_id'],sp['control_head'],sp['control_sequence'],sp['content_epoch'],sp['state'])!=(row['app_id'],row['head'],row['sequence'],row['epoch'],STATE_MAP[row['phase']]):raise ValueError()
        except (ValueError,KeyError,TypeError):raise E('AUTH_STORE_CORRUPT') from None
        return row
    def _load(self,space):
        row=self._row(space);c=self._storage.connection
        try:
            st=restore_public_replay(self._provider,row['app_id'],space,row['head'],row['replay_digest'],row['replay'],minimum_sequence=from_u64(row['sequence']))
            if st.sequence!=from_u64(row['sequence']) or st.epoch!=from_u64(row['epoch']):raise ValueError()
            keys={from_u64(r['epoch']):dict(r) for r in c.execute('SELECT * FROM auth_epoch_keys WHERE space_id=?',(space,))}
            mats={r['material_id']:dict(r) for r in c.execute('SELECT * FROM auth_materials WHERE space_id=?',(space,))}
            seen=set()
            for mid,m in mats.items():
                if sha(m['encrypted_material'])!=mid:raise ValueError()
                unpack_material(m['encrypted_material'])
                ep=from_u64(m['epoch']);k=keys[ep];a=st.control(m['anchor'])
                if (k['anchor'],k['key_check'])!=(m['anchor'],m['key_check']) or a.body[3]!=ep or a.anchor_id!=a.id:raise ValueError()
                seen.add(ep)
            if seen!=set(keys):raise ValueError()
            st._key_checks={ep:k['key_check'] for ep,k in keys.items()}
            base=st.status()['state']
            if row['phase']=='ACTIVE':
                if base!='EPOCH_PENDING' or row['active_material'] not in mats or mats[row['active_material']]['anchor']!=st.epoch_anchor.id:raise ValueError()
            elif base!=row['phase']:raise ValueError()
            old=self._cache.get(space)
            if old and old[0]==row['revision'] and old[1]==row['replay_digest']:
                st._active=old[2]
            return row,st
        except (AuthError,StoreError,ValueError,KeyError,TypeError):raise E('AUTH_STORE_CORRUPT') from None
    def _notify(self,stage):self._storage._observe(stage)
    def _persist(self,old,st,material):
        """Persist state+material+key history+queue transition under one write lock."""
        store=self._storage;store._writable();c=store.connection
        raw=export_public_replay(st);phase=st.status()['state']
        mid=old['active_material'] if old is not None else None
        if old is not None and from_u64(old['epoch'])!=st.epoch:mid=None
        if material is not None:mid=sha(material)
        row=dict(zip(ROW_FIELDS,[st.space_id,st.app_id,raw,hashed('auth-local/replay',[raw]),st.head,u64(st.sequence),u64(st.epoch),u64(1 if old is None else from_u64(old['revision'])+1),phase,mid]))
        row['row_digest']=row_hash(row)
        required=self._failed.get(st.space_id)
        if required is not None and required!=row['replay_digest']:raise E('AUTH_PERSISTENCE_UNCERTAIN')
        attempted=False;self._busy=True
        try:
            self._notify('auth.before_begin');c.execute('BEGIN IMMEDIATE');self._notify('auth.after_begin')
            if old is not None:
                live=self._row(st.space_id)
                if live['row_digest']!=old['row_digest']:raise E('STALE_DECISION')
                c.execute('UPDATE spaces SET control_head=?,control_sequence=?,content_epoch=?,state=? WHERE space_id=?',(row['head'],row['sequence'],row['epoch'],STATE_MAP[phase],st.space_id))
                c.execute('UPDATE auth_spaces SET '+','.join(k+'=?' for k in ROW_FIELDS[1:])+',row_digest=? WHERE space_id=?',tuple(row[k] for k in ROW_FIELDS[1:])+(row['row_digest'],st.space_id))
            else:
                if c.execute('SELECT 1 FROM spaces WHERE space_id=?',(st.space_id,)).fetchone():raise E('AUTH_SPACE_EXISTS')
                c.execute('INSERT INTO spaces VALUES(?,?,?,?,?,?,?)',(st.space_id,st.app_id,row['head'],row['sequence'],row['epoch'],STATE_MAP[phase],b''))
                c.execute('INSERT INTO auth_spaces VALUES('+','.join('?' for _ in range(11))+')',tuple(row[k] for k in ROW_FIELDS)+(row['row_digest'],))
            self._notify('auth.after_row')
            if material is not None:
                active=st._active;check=hashed('auth-local/epoch-key-check',[active.secret])
                existing=c.execute('SELECT anchor,key_check FROM auth_epoch_keys WHERE space_id=? AND epoch=?',(st.space_id,u64(active.epoch))).fetchone()
                if existing is not None and tuple(existing)!=(active.anchor_id,check):raise E('EPOCH_SECRET_CONFLICT')
                c.execute('INSERT OR IGNORE INTO auth_epoch_keys VALUES(?,?,?,?)',(st.space_id,u64(active.epoch),active.anchor_id,check))
                if c.execute('SELECT count(*) FROM auth_materials WHERE space_id=?',(st.space_id,)).fetchone()[0]>=1024 and c.execute('SELECT 1 FROM auth_materials WHERE space_id=? AND material_id=?',(st.space_id,mid)).fetchone() is None:raise E('AUTH_MATERIAL_LIMIT')
                c.execute('INSERT OR IGNORE INTO auth_materials VALUES(?,?,?,?,?,?)',(st.space_id,mid,u64(active.epoch),active.anchor_id,check,material))
            self._notify('auth.after_material')
            if old is not None and row['epoch']!=old['epoch']:
                c.execute("UPDATE outbox SET state='rebase-required' WHERE state IN ('pending','in-flight') AND envelope_id IN (SELECT envelope_id FROM envelopes WHERE space_id=?)",(st.space_id,))
                c.execute('DELETE FROM actor_states WHERE space_id=?',(st.space_id,))
            self._notify('auth.after_outbox');self._notify('auth.before_commit');attempted=True;c.execute('COMMIT');self._notify('auth.after_commit')
            self._cache[st.space_id]=(row['revision'],row['replay_digest'],st._active)
            self._failed.pop(st.space_id,None)
        except BaseException as exc:
            self._failed[st.space_id]=row['replay_digest']
            self._cache.pop(st.space_id,None)
            failed=False
            if c.in_transaction:
                try:c.execute('ROLLBACK')
                except sqlite3.Error:failed=True
            if attempted or failed:
                self._cache.pop(st.space_id,None);raise E('AUTH_OUTCOME_UNKNOWN') from None
            if isinstance(exc,(StoreError,AuthError)):raise
            if isinstance(exc,sqlite3.Error):raise sqlite_error(exc) from None
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            raise E('AUTH_UPDATE_ABORTED') from None
        finally:self._busy=False
    def enroll(self,app,space,genesis):
        self._enter(True);st=AuthorityState(self._provider,app,space,genesis)
        if self._storage.connection.execute('SELECT 1 FROM auth_spaces WHERE space_id=?',(space,)).fetchone():
            old,known=self._load(space)
            if known._genesis!=genesis or known.app_id!=app:raise E('TRUST_ANCHOR')
            return 'DUPLICATE'
        self._persist(None,st,None);return 'ENROLLED'
    def _change(self,space,fn):
        self._enter(True);old,st=self._load(space);error=None
        try:result=fn(st)
        except AuthError as exc:
            if exc.code not in TERMINAL:raise
            error=exc;result=None
        if result!='DUPLICATE':self._persist(old,st,None)
        elif self._failed.get(space)==old['replay_digest']:
            # Exact target is already durable (lost reply), not an old-history duplicate.
            self._failed.pop(space,None)
        if error is not None:raise error
        return result
    def observe(self,space,raw):return self._change(space,lambda st:st.observe(raw))
    def provide_membership(self,space,pages):return self._change(space,lambda st:st.provide_membership(pages))
    def activate(self,space,certificate,recipient_secret,package,ids,manifest,seeds):
        self._enter(True);old,st=self._load(space)
        raw=pack_material(certificate,package,ids,manifest,seeds)
        certificate,package,ids,manifest,seeds=unpack_material(raw)
        result=st.activate(certificate,recipient_secret,package,ids,manifest,seeds)
        self._persist(old,st,raw);return result
    def reactivate(self,space,recipient_secret):
        self._enter(True);row,st=self._load(space)
        mid=row['active_material']
        if mid is None:raise E('AUTH_MATERIAL_REQUIRED')
        raw=self._storage.connection.execute('SELECT encrypted_material FROM auth_materials WHERE space_id=? AND material_id=?',(space,mid)).fetchone()
        if raw is None:raise E('AUTH_STORE_CORRUPT')
        cert,package,ids,manifest,seeds=unpack_material(raw[0])
        return self.activate(space,cert,recipient_secret,package,ids,manifest,seeds)
    def status(self,space):
        self._enter();row,st=self._load(space);s=st.status()
        s.update({'revision':from_u64(row['revision']),'durable_phase':row['phase'],'restore_read_only':self._storage.restore_read_only,
                  'automerge_validated':False,'production_qualified':False,'authority_persisted':True})
        if space in self._failed:s['state']='AUTH_PERSISTENCE_UNCERTAIN'
        return s
    def pin(self,space):
        self._enter();r=self._row(space)
        return {'space_id':space.hex(),'store_generation':self._storage.generation.hex(),'head':r['head'].hex(),
                'sequence':from_u64(r['sequence']),'revision':from_u64(r['revision']),'replay_digest':r['replay_digest'].hex()}
    def _check_pins(self,pins):
        if type(pins) not in (list,tuple):raise E('AUTH_PIN_STALE')
        for pin in pins:
            try:
                if set(pin)!={'space_id','store_generation','head','sequence','revision','replay_digest'}:raise ValueError()
                if type(pin['sequence']) is not int or type(pin['revision']) is not int or min(pin['sequence'],pin['revision'])<0:raise ValueError()
                space=bytes.fromhex(pin['space_id']);r,st=self._load(space)
                if pin['store_generation']!=self._storage.generation.hex() or from_u64(r['revision'])<pin['revision'] or st.sequence<pin['sequence']:raise ValueError()
                if (st._sequences.get(pin['sequence']) if pin['sequence'] else space)!=bytes.fromhex(pin['head']):raise ValueError()
                if from_u64(r['revision'])==pin['revision'] and r['replay_digest'].hex()!=pin['replay_digest']:raise ValueError()
            except (ValueError,KeyError,TypeError,StoreError,AuthError):raise E('AUTH_PIN_STALE') from None
    def _authorize(self,certificate,header,sign_public,secret):
        self._enter(True)
        if header[1] in self._failed:raise E('AUTH_PERSISTENCE_UNCERTAIN')
        row,st=self._load(header[1]);permit=st.authorize(certificate,'write')
        if header[0]!=st.app_id or header[1]!=st.space_id or header[2]!=st.epoch or header[13]!=st.head or header[5]!=permit.device_id or hashed('device-id',[st.app_id,sign_public])!=permit.device_id:raise E('AUTH_CONTEXT_MISMATCH')
        check=hashed('auth-local/epoch-key-check',[secret])
        if check!=st._key_checks.get(st.epoch):raise E('EPOCH_SECRET_MISMATCH')
        return row,permit,check
    def _bind(self,prepared,row,permit,certificate,key_check):
        c=BoundWrite(prepared,prepared.space_id,row['head'],from_u64(row['sequence']),from_u64(row['epoch']),from_u64(row['revision']),permit.device_id,certificate,key_check,row['active_material'],self._storage.fencing_token,self,b'')
        return replace(c,_seal=hmac.digest(self._seal_key,c.sealed_bytes(),'sha256'))
    def _validate_ticket(self,candidate):
        try:
            if type(candidate) is not BoundWrite or candidate._owner is not self or type(candidate._seal) is not bytes:raise ValueError()
            if not hmac.compare_digest(hmac.digest(self._seal_key,candidate.sealed_bytes(),'sha256'),candidate._seal):raise ValueError()
            candidate.prepared.validate()
        except Exception:raise E('CANDIDATE_INVALID') from None
    def _guard(self,ticket,p,token):
        self._validate_ticket(ticket)
        if ticket.prepared.fingerprint!=p.fingerprint or token!=ticket.fence or self._storage.fencing_token!=token:raise E('CANDIDATE_INVALID')
        if ticket.space_id in self._failed:raise E('STALE_DECISION')
        r=self._row(ticket.space_id)
        if (r['phase'],r['head'],r['sequence'],r['epoch'],r['revision'],r['active_material'])!=('ACTIVE',ticket.head,u64(ticket.sequence),u64(ticket.epoch),u64(ticket.revision),ticket.material_id):raise E('STALE_DECISION')
        if self._cache.get(ticket.space_id,(None,))[0]!=r['revision']:raise E('STALE_DECISION')
        key=self._storage.connection.execute('SELECT key_check FROM auth_epoch_keys WHERE space_id=? AND epoch=?',(ticket.space_id,u64(ticket.epoch))).fetchone()
        if key is None or key[0]!=ticket.key_check:raise E('STALE_DECISION')
    def _record_commit(self,p):
        t=self._pending;c=self._storage.connection
        values=(p.operation_id,t.space_id,t.head,u64(t.sequence),u64(t.epoch),u64(t.revision),t.device_id,t.certificate,t.key_check,t.material_id,p.fingerprint)
        c.execute('INSERT INTO auth_commits VALUES('+','.join('?' for _ in range(12))+')',values+(proof_hash(values),))
        self._notify('commit.after_authority_proof')
    def commit(self,candidate):
        self._enter(True);self._validate_ticket(candidate);self._guard(candidate,candidate.prepared,candidate.fence)
        self._pending=candidate
        try:return self._storage.commit(candidate.prepared,fencing_token=candidate.fence)
        finally:self._pending=None
    def pending(self,*,limit=128):
        self._enter()
        rows=self._storage.pending(limit=limit);out=[]
        for row in rows:
            header=decode(decode(row['envelope'])[0]);r,st=self._load(header[1])
            if r['phase']=='ACTIVE' and st.active_epoch==header[2]:out.append(row)
        return out
    def audit(self):
        from .audit import audit
        self._enter();return audit(self)
    def export_snapshot(self,dest):
        self._enter();return self._storage.export_snapshot(dest)
    @classmethod
    def restore_snapshot(cls,source,dest,*,provider,allow_unpatched_sqlite=False):
        from par_store.recovery import restore_snapshot
        def verify_stage(stage):
            with cls.open(stage,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as candidate:
                if not candidate.audit()['valid']:raise E('AUTH_STORE_CORRUPT')
        result=restore_snapshot(Path(source),Path(dest),allow_unpatched_sqlite=allow_unpatched_sqlite,store_type=BoundStorage,stage_validator=verify_stage)
        with cls.open(dest,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as s:
            if not s.audit()['valid']:raise E('AUTH_STORE_CORRUPT')
        return result
    @classmethod
    def migrate_empty(cls,root,*,provider,allow_unpatched_sqlite=False,observer=None):
        with Store.open(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite) as s:
            c=s.connection
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            if any(c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables if t not in ('store_metadata','writer_fences','local_settings')):raise E('LEGACY_DATA_REQUIRES_IMPORT')
            s._writable();attempted=False
            try:
                c.execute('BEGIN IMMEDIATE')
                if observer:observer('migration.after_begin')
                for statement in schema.statements():c.execute(statement)
                if observer:observer('migration.after_schema')
                c.execute('UPDATE store_metadata SET profile_digest=?',(schema.digest(),));c.execute('PRAGMA user_version=2')
                if observer:observer('migration.before_commit')
                attempted=True;c.execute('COMMIT')
                if observer:observer('migration.after_commit')
            except BaseException as exc:
                if c.in_transaction:c.execute('ROLLBACK')
                if attempted:raise E('AUTH_OUTCOME_UNKNOWN') from None
                if isinstance(exc,sqlite3.Error):raise sqlite_error(exc) from None
                if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
                raise E('AUTH_UPDATE_ABORTED') from None
        return cls.open(root,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite)
