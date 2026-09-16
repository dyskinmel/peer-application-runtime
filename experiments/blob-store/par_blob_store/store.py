"""Schema3 local extension, not a native storage engine or public P2P protocol."""
from __future__ import annotations
from dataclasses import replace
import hmac, sqlite3
from pathlib import Path
from par_auth_store import AuthorityStore
from par_auth_store.backend import BoundStorage
from par_auth.membership import member_certificate
from par_store.model import u64, from_u64, fixed
from par_store.store import sqlite_error
from par_store.errors import StoreError
from par_wire.codec import encode, decode
from .backend import BlobStorage
from .model import BlobWrite, Attachment, from_prepared, verify_manifest, sha, inspect_attachment
from .errors import BlobStoreError as E
from . import schema

BIND_COLUMNS=['typed_id','locator','app_id','space_id','epoch','object_id','object_kind','chunk_index','key_generation','plain_size','sealed_size','header_bytes']
def binding_row(b):
    return (b.typed_id,b.locator,b.app,b.space,u64(b.epoch),b.object_id,b.kind,u64(b.index),u64(b.key_generation),b.plain_size,b.sealed_size,b.header_bytes)

class BlobStore(AuthorityStore):
    def __init__(self,storage,provider):
        super().__init__(storage,provider);self._pending_blob=None
    @classmethod
    def create(cls,root,*,provider,allow_unpatched_sqlite=False):
        return cls(BlobStorage.create(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite),provider)
    @classmethod
    def open(cls,root,*,provider,allow_unpatched_sqlite=False,expected_pins=()):
        self=cls(BlobStorage.open(Path(root),allow_unpatched_sqlite=allow_unpatched_sqlite),provider)
        try:
            if not self.audit()['valid']:raise E('BLOB_STORE_CORRUPT')
            self._check_pins(expected_pins)
            if not self._storage.restore_read_only:
                for r in list(self._storage.connection.execute("SELECT space_id FROM auth_spaces WHERE phase='ACTIVE'")):
                    row,st=self._load(r[0]);self._persist(row,st,None)
            return self
        except BaseException:self.close();raise
    def _blob_mac(self,bound,manifest):
        return hmac.digest(self._seal_key,b'PAR-BLOB-LOCAL-1\0'+encode([bound._seal,sha(manifest)]),'sha256')
    def _bind_blob(self,bound,manifest):
        return BlobWrite(bound,manifest,self._blob_mac(bound,manifest))
    def _verify_blob(self,candidate):
        try:
            if type(candidate) is not BlobWrite or type(candidate.manifest) is not bytes:raise ValueError()
            self._validate_ticket(candidate.bound)
            if not hmac.compare_digest(candidate._seal,self._blob_mac(candidate.bound,candidate.manifest)):raise ValueError()
        except Exception:raise E('CANDIDATE_INVALID') from None
        _,_,bindings=from_prepared(candidate.prepared)
        row,st=self._load(candidate.bound.space_id)
        cert=member_certificate(self._provider,st.app_id,st.membership_at(candidate.bound.head),candidate.bound.certificate)
        verify_manifest(self._provider,cert[3],candidate.prepared,bindings,candidate.manifest)
        return bindings
    def commit(self,candidate):
        self._enter(True)
        if type(candidate) is BlobWrite:
            self._verify_blob(candidate)
            self._pending_blob=candidate
            try:return super().commit(candidate.bound)
            finally:self._pending_blob=None
        if getattr(getattr(candidate,'prepared',None),'blocks',()):raise E('ATTACHMENT_BINDING_REQUIRED')
        return super().commit(candidate)
    def _guard(self,ticket,p,token):
        super()._guard(ticket,p,token)
        if p.blocks and self._pending_blob is None:raise E('ATTACHMENT_BINDING_REQUIRED')
        if self._pending_blob is not None:
            if self._pending_blob.bound is not ticket:raise E('CANDIDATE_INVALID')
            _,_,bindings=from_prepared(p)
            if self._storage.connection.in_transaction:
                for b,raw in zip(bindings,p.blocks):
                    if self._storage.read_block(b.locator)!=raw:raise E('BLOCK_CORRUPT')
    def _record_commit(self,p):
        super()._record_commit(p)
        c=self._storage.connection;candidate=self._pending_blob
        if candidate is None:
            if p.blocks:raise E('ATTACHMENT_BINDING_REQUIRED')
            c.execute('INSERT INTO blob_commit_roots VALUES(?,?,0,NULL)',(p.operation_id,p.envelope_id))
            return
        _,_,bindings=from_prepared(p)
        c.execute('INSERT INTO blob_commit_roots VALUES(?,?,1,?)',(p.operation_id,p.envelope_id,candidate.manifest))
        self._notify('blob.after_manifest')
        for index,b in enumerate(bindings):
            values=binding_row(b)
            old=c.execute('SELECT * FROM blob_objects WHERE typed_id=? OR locator=?',(b.typed_id,b.locator)).fetchall()
            if old:
                if len(old)!=1 or tuple(old[0][k] for k in BIND_COLUMNS)!=values:raise E('BLOCK_ALIAS_CONFLICT')
            else:c.execute('INSERT INTO blob_objects VALUES('+','.join('?' for _ in values)+')',values)
            self._notify('blob.after_alias')
            c.execute('INSERT INTO blob_references VALUES(?,?,?)',(p.envelope_id,index,b.typed_id))
            self._notify('blob.after_reference')
        self._notify('blob.after_bindings')
    def audit(self):
        from .audit import audit
        self._enter();return audit(self)
    def attachments(self,eid):
        self._enter();fixed(eid,32)
        if not self.audit()['valid']:raise E('BLOB_STORE_CORRUPT')
        c=self._storage.connection
        if c.execute('SELECT 1 FROM blob_commit_roots WHERE envelope_id=?',(eid,)).fetchone() is None:raise E('COMMIT_NOT_FOUND')
        out=[]
        for r in c.execute('SELECT b.* FROM blob_references r JOIN blob_objects b USING(typed_id) WHERE r.envelope_id=? ORDER BY r.position',(eid,)):
            out.append(inspect_attachment(Attachment(r['typed_id'],r['header_bytes'],self._storage.read_block(r['locator']))))
        return tuple(out)
    def read_attachment(self,eid,position,epoch_secret):
        from par_crypto import objects
        if type(position) is not int or position<0:raise E('BLOB_INPUT')
        bindings=self.attachments(eid)
        if position>=len(bindings):raise E('ATTACHMENT_NOT_FOUND')
        b=bindings[position];raw=self._storage.read_block(b.locator)
        return objects.open_block(self._provider,epoch_secret,decode(b.header_bytes),raw)
    def orphan_report(self):
        """Inventory only. No GC until reader/lease/recovery pins are implemented."""
        self._enter()
        if not self.audit()['valid']:raise E('BLOB_STORE_CORRUPT')
        refs={r[0].hex() for r in self._storage.connection.execute('SELECT locator FROM blob_objects')}
        # Non-Blob base files may also be referenced; never label them reclaimable.
        refs|={r[0].hex() for r in self._storage.connection.execute('SELECT block_id FROM blocks')}
        names=sorted(p.name for p in (self._storage.root/'blocks').iterdir() if p.is_file() and not p.is_symlink())
        return {'unreferenced_locators':[n for n in names if n not in refs],'deletion_performed':False,'gc_qualified':False}
    @classmethod
    def restore_snapshot(cls,source,dest,*,provider,allow_unpatched_sqlite=False):
        from par_store.recovery import restore_snapshot
        def verify_stage(stage):
            with cls.open(stage,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as candidate:
                if not candidate.audit()['valid']:raise E('BLOB_STORE_CORRUPT')
        return restore_snapshot(Path(source),Path(dest),allow_unpatched_sqlite=allow_unpatched_sqlite,store_type=BlobStorage,stage_validator=verify_stage)
    @classmethod
    def migrate_v2(cls,root,*,provider,allow_unpatched_sqlite=False,observer=None):
        with AuthorityStore.open(Path(root),provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite) as old:
            storage=old._storage;storage._writable();c=storage.connection
            if not old.audit()['valid']:raise E('BLOB_STORE_CORRUPT')
            if c.execute('SELECT count(*) FROM blocks').fetchone()[0] or c.execute('SELECT count(*) FROM envelope_blocks').fetchone()[0]:raise E('LEGACY_BLOCKS_REQUIRE_IMPORT')
            attempted=False
            try:
                c.execute('BEGIN IMMEDIATE')
                if observer:observer('blob_migration.after_begin')
                for stmt in schema.statements():c.execute(stmt)
                c.execute('INSERT INTO blob_commit_roots SELECT operation_id,commit_id,0,NULL FROM commit_ledger')
                if observer:observer('blob_migration.after_schema')
                c.execute('UPDATE store_metadata SET profile_digest=?',(schema.digest(),));c.execute('PRAGMA user_version=3')
                if observer:observer('blob_migration.before_commit')
                attempted=True;c.execute('COMMIT')
                if observer:observer('blob_migration.after_commit')
            except BaseException as exc:
                if c.in_transaction:c.execute('ROLLBACK')
                if attempted:raise E('MIGRATION_OUTCOME_UNKNOWN') from None
                if isinstance(exc,StoreError):raise
                if isinstance(exc,sqlite3.Error):raise sqlite_error(exc) from None
                if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
                raise E('MIGRATION_ABORTED') from None
        return cls.open(root,provider=provider,allow_unpatched_sqlite=allow_unpatched_sqlite)
