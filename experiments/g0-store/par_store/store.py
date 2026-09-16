"""Executable local storage experiment. No crypto, network, or native qualification.

One instance owns the cooperating POSIX writer lock for its lifetime; methods are
synchronous and must not be reentered from the optional stage observer.
"""
from __future__ import annotations
import errno, os, re, secrets, sqlite3
from pathlib import Path
from .errors import StoreError
from .model import PreparedCommit,CommitReceipt,fixed,u64,from_u64,sha,SCHEMA_DIGEST,wal_reset_fixed,require_sqlite
from .fs import WriterLock,BlockPort,safe,sync_dir

ROOT=Path(__file__).resolve().parents[3]
BASE_DDL=ROOT/'baseline/spec-00.02.00/protocol/storage-v1.sql'
OVERLAY=Path(__file__).resolve().parents[1]/'schema-overlay.sql'

def profile_digest():return sha(BASE_DDL.read_bytes()+b'\x00'+OVERLAY.read_bytes()+SCHEMA_DIGEST)

def sqlite_error(exc: sqlite3.Error, op=None):
    raw=getattr(exc,'sqlite_errorcode',None);base=(raw & 255) if raw is not None else None
    code={sqlite3.SQLITE_FULL:'SQLITE_FULL',sqlite3.SQLITE_BUSY:'SQLITE_BUSY',sqlite3.SQLITE_LOCKED:'SQLITE_BUSY',
          sqlite3.SQLITE_INTERRUPT:'SQLITE_INTERRUPT',sqlite3.SQLITE_CONSTRAINT:'SQLITE_CONSTRAINT',
          sqlite3.SQLITE_CORRUPT:'CORRUPT_STORE',sqlite3.SQLITE_NOTADB:'CORRUPT_STORE',sqlite3.SQLITE_READONLY:'READ_ONLY'}.get(base,'STORAGE_ERROR')
    return StoreError(code,operation_id=op,sqlite_code=base)

class Store:
    USER_VERSION=1
    @classmethod
    def schema_sql(cls):return BASE_DDL.read_text()+'\n'+OVERLAY.read_text()
    @classmethod
    def schema_profile(cls):return profile_digest()
    @classmethod
    def schema_matches(cls,c):
        from .schema import matches
        return matches(c)
    def _authorize_commit(self,p,token):pass
    def _commit_authority_meta(self,p):pass
    def _envelope_state(self,p):return 'applied'
    def __init__(self):
        self.connection=None;self._lock=None;self.closed=True;self.observer=None;self._busy=False
        self.fencing_token=None;self.restore_read_only=False
    @classmethod
    def create(cls,root:Path,*,allow_unpatched_sqlite=False):
        require_sqlite(sqlite3.sqlite_version,allow_unpatched_sqlite)
        root=safe(Path(root))
        if (root/'store.sqlite').exists():raise StoreError('STORE_EXISTS')
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        return cls._connect(root,create=True)
    @classmethod
    def open(cls,root:Path,*,allow_unpatched_sqlite=False):
        require_sqlite(sqlite3.sqlite_version,allow_unpatched_sqlite)
        root=safe(Path(root));db=safe(root/'store.sqlite')
        if not db.is_file():raise StoreError('STORE_MISSING')
        return cls._connect(root,create=False)
    @classmethod
    def _connect(cls,root,create):
        self=cls();self.root=root
        try:
            self._lock=WriterLock(root)
            db=safe(root/'store.sqlite')
            for suffix in ('-wal','-shm','-journal'):safe(root/('store.sqlite'+suffix))
            if create:
                fd=os.open(db,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
            kwargs={'isolation_level':None,'timeout':0.05,'uri':True}
            if hasattr(sqlite3,'LEGACY_TRANSACTION_CONTROL'):kwargs['autocommit']=sqlite3.LEGACY_TRANSACTION_CONTROL
            self.connection=sqlite3.connect(db.as_uri()+'?mode=rw',**kwargs)
            c=self.connection;c.row_factory=sqlite3.Row
            if not create:
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise StoreError('CORRUPT_STORE')
                if c.execute('PRAGMA user_version').fetchone()[0]!=cls.USER_VERSION:raise StoreError('SCHEMA_MISMATCH')
                if not cls.schema_matches(c):raise StoreError('SCHEMA_MISMATCH')
                row=c.execute('SELECT schema_version,profile_digest FROM store_metadata WHERE singleton=1').fetchone()
                if row is None or row['schema_version']!=1 or row['profile_digest']!=cls.schema_profile():raise StoreError('SCHEMA_MISMATCH')
            c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA foreign_keys=ON')
            c.execute('PRAGMA temp_store=MEMORY');c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA busy_timeout=50')
            c.execute('PRAGMA wal_autocheckpoint=1000')
            if create:
                c.executescript('BEGIN IMMEDIATE;\n'+cls.schema_sql())
                generation=secrets.token_bytes(16)
                c.execute('INSERT INTO store_metadata VALUES(1,1,?,?)',(generation,cls.schema_profile()))
                c.execute('INSERT INTO local_settings VALUES(1,0)');c.execute('PRAGMA user_version='+str(cls.USER_VERSION));c.execute('COMMIT');sync_dir(root)
            self.generation=c.execute('SELECT generation FROM store_metadata').fetchone()[0]
            self.restore_read_only=bool(c.execute('SELECT read_only_restore FROM local_settings').fetchone()[0])
            self.closed=False;self.block_port=BlockPort(root,self._observe)
            self._settings()
            if not self.restore_read_only:self.rotate_fence()
            return self
        except sqlite3.Error as exc:
            self.close();raise sqlite_error(exc) from None
        except BaseException:
            self.close();raise
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if self.connection is not None:
            try:self.connection.close()
            finally:self.connection=None
        if self._lock is not None:self._lock.close();self._lock=None
        self.closed=True
    def _alive(self):
        if self.closed or self.connection is None:raise StoreError('STORE_CLOSED')
    def _writable(self):
        self._alive()
        if self.restore_read_only:raise StoreError('RESTORE_READ_ONLY')
        if self._busy:raise StoreError('REENTRANT_OPERATION')
        self._settings()
    def _settings(self):
        self._alive();c=self.connection
        try:
            found=(c.execute('PRAGMA journal_mode').fetchone()[0],c.execute('PRAGMA synchronous').fetchone()[0],
                   c.execute('PRAGMA foreign_keys').fetchone()[0],c.execute('PRAGMA temp_store').fetchone()[0])
        except sqlite3.Error as exc:
            raise sqlite_error(exc) from None
        if found!=('wal',2,1,2):raise StoreError('SETTINGS_MISMATCH')
    def _observe(self,stage):
        if self.observer is not None:self.observer(stage)
    def diagnostics(self):
        self._alive();c=self.connection;fixed_patch=wal_reset_fixed(sqlite3.sqlite_version)
        return {'journal_mode':c.execute('PRAGMA journal_mode').fetchone()[0],
            'synchronous':c.execute('PRAGMA synchronous').fetchone()[0],
            'foreign_keys':c.execute('PRAGMA foreign_keys').fetchone()[0],
            'sqlite_version':sqlite3.sqlite_version,'sqlite_source_id':c.execute('SELECT sqlite_source_id()').fetchone()[0],
            'compile_options':[x[0] for x in c.execute('PRAGMA compile_options')],
            'wal_reset_fix_known':fixed_patch,'warnings':[] if fixed_patch else ['UNPATCHED_SQLITE_EXPERIMENT_ONLY'],
            'storage_class':'POSIX_LOCAL_PROCESS_CRASH_CANDIDATE',
            'payload_contract':'PRESEALED_OPAQUE_BYTES','cryptography_verified':False,
            'production_qualified':False,'physical_power_loss_tested':False,'restore_read_only':self.restore_read_only}
    def _transaction(self,fn):
        self._writable();c=self.connection
        try:
            c.execute('BEGIN IMMEDIATE');value=fn();c.execute('COMMIT');return value
        except BaseException:
            if c.in_transaction:c.execute('ROLLBACK')
            raise
    def rotate_fence(self):
        self._writable();token=secrets.token_bytes(16);owner=secrets.token_bytes(16)
        def body():self.connection.execute('INSERT OR REPLACE INTO writer_fences VALUES(?,?,?)',(self.generation,token,owner))
        self._transaction(body);self.fencing_token=token;return token
    def configure_space(self,space_id,app_id,epoch,control_head):
        self._writable();fixed(space_id,32);fixed(control_head,32);u64(epoch)
        if type(app_id) is not str or re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,127}',app_id) is None:raise StoreError('INVALID_INPUT')
        def body():
            self.connection.execute('INSERT INTO spaces VALUES(?,?,?,?,?,?,?)',(space_id,app_id,control_head,u64(1),u64(epoch),'ready',b''))
        try:self._transaction(body)
        except sqlite3.Error as exc:raise sqlite_error(exc) from None
    def reserve_nonce(self,operation_id,input_digest,key_context,nonce):
        self._writable();fixed(operation_id,16);fixed(input_digest,32);fixed(key_context,32);fixed(nonce,24)
        rid=secrets.token_bytes(16)
        def body():
            c=self.connection
            old=c.execute('SELECT input_digest FROM local_operation_intents WHERE operation_id=?',(operation_id,)).fetchone()
            if old is not None and old[0]!=input_digest:raise StoreError('OPERATION_CONFLICT',operation_id=operation_id)
            if c.execute('SELECT 1 FROM issued_nonces WHERE key_context=? AND nonce=?',(key_context,nonce)).fetchone():raise StoreError('NONCE_REUSED')
            if c.execute('SELECT 1 FROM commit_ledger WHERE operation_id=?',(operation_id,)).fetchone():raise StoreError('OPERATION_ALREADY_COMMITTED',operation_id=operation_id)
            c.execute('INSERT OR IGNORE INTO local_operation_intents VALUES(?,?)',(operation_id,input_digest))
            c.execute('INSERT INTO issued_nonces VALUES(?,?,?)',(key_context,nonce,input_digest))
            c.execute('INSERT INTO local_nonce_reservations VALUES(?,?,?,?,NULL)',(rid,operation_id,key_context,nonce))
        try:self._transaction(body);return rid
        except sqlite3.Error as exc:raise sqlite_error(exc,operation_id) from None
    def lookup_operation(self,operation_id,input_digest):
        self._alive()
        if self._busy or self.connection.in_transaction:raise StoreError('REENTRANT_OPERATION')
        return self._lookup_operation(operation_id,input_digest)
    def _lookup_operation(self,operation_id,input_digest):
        self._alive();fixed(operation_id,16);fixed(input_digest,32)
        try:
            row=self.connection.execute('''SELECT l.*,m.store_generation,m.storage_class FROM commit_ledger l
              LEFT JOIN local_commit_meta m USING(operation_id) WHERE operation_id=?''',(operation_id,)).fetchone()
            if row is None:return None
            if row['input_digest']!=input_digest:raise StoreError('OPERATION_CONFLICT',operation_id=operation_id)
            if row['store_generation'] is None:raise StoreError('CORRUPT_STORE')
            return CommitReceipt(operation_id,input_digest,row['commit_id'],row['receipt_encrypted'],row['store_generation'],row['storage_class'])
        except sqlite3.Error as exc:raise sqlite_error(exc,operation_id) from None
    def _check_state(self,p,token):
        c=self.connection;row=c.execute('SELECT fencing_token FROM writer_fences WHERE store_generation=?',(self.generation,)).fetchone()
        if row is None or row[0]!=token:raise StoreError('FENCE_STALE')
        row=c.execute('SELECT state,content_epoch FROM spaces WHERE space_id=?',(p.space_id,)).fetchone()
        if row is None or row['state']!='ready':raise StoreError('SPACE_NOT_READY')
        if row['content_epoch']!=u64(p.epoch):raise StoreError('EPOCH_MISMATCH')
        row=c.execute('SELECT * FROM local_nonce_reservations WHERE reservation_id=?',(p.reservation_id,)).fetchone()
        if row is None or row['operation_id']!=p.operation_id or row['consumed_by'] is not None:raise StoreError('RESERVATION_MISMATCH')
        row=c.execute('SELECT input_digest FROM local_operation_intents WHERE operation_id=?',(p.operation_id,)).fetchone()
        if row is None or row[0]!=p.input_digest:raise StoreError('OPERATION_CONFLICT')
        a=c.execute('SELECT * FROM actor_states WHERE space_id=? AND object_id=? AND actor_id=?',(p.space_id,p.object_id,p.actor_id)).fetchone()
        if a is None:
            if p.sequence!=1 or p.previous_envelope is not None:raise StoreError('ACTOR_CONFLICT')
        elif a['generation']!=p.actor_generation or from_u64(a['last_sequence'])+1!=p.sequence or a['previous_envelope']!=p.previous_envelope:
            raise StoreError('ACTOR_CONFLICT')
    def commit(self,p:PreparedCommit,*,fencing_token:bytes):
        self._writable()
        if type(p) is not PreparedCommit:raise StoreError('INVALID_INPUT')
        p.validate();fixed(fencing_token,16)
        old=self.lookup_operation(p.operation_id,p.input_digest)
        if old:
            row=self.connection.execute('SELECT prepared_digest FROM local_commit_meta WHERE operation_id=?',(p.operation_id,)).fetchone()
            if row[0]!=p.fingerprint:raise StoreError('OPERATION_CONFLICT',operation_id=p.operation_id)
            return old
        c=self.connection;attempted_commit=False;self._busy=True
        try:
            self._check_state(p,fencing_token)
            block_ids=[self.block_port.publish(b) for b in p.blocks]
            self._observe('commit.before_begin');c.execute('BEGIN IMMEDIATE');self._observe('commit.after_begin')
            self._authorize_commit(p,fencing_token)
            self._check_state(p,fencing_token)
            eid=p.envelope_id
            c.execute('INSERT INTO envelopes VALUES(?,?,?,?,?,?,?,?,?)',(eid,p.space_id,p.object_id,u64(p.epoch),p.actor_id,u64(p.sequence),p.change_hash,p.envelope,self._envelope_state(p)))
            self._observe('commit.after_envelope')
            c.execute('INSERT INTO commit_ledger VALUES(?,?,?,?,?)',(p.operation_id,p.input_digest,p.space_id,eid,p.encrypted_receipt));self._observe('commit.after_ledger')
            c.execute('INSERT OR REPLACE INTO actor_states VALUES(?,?,?,?,?,?)',(p.space_id,p.object_id,p.actor_id,p.actor_generation,u64(p.sequence),eid));self._observe('commit.after_actor')
            c.execute('INSERT INTO catalog VALUES(?,?,?,?,?,?,?) ON CONFLICT(space_id,object_id) DO UPDATE SET encrypted_snapshot_ref=excluded.encrypted_snapshot_ref',
                      (p.space_id,p.object_id,1,SCHEMA_DIGEST,p.encrypted_cache,0,b''));self._observe('commit.after_catalog')
            c.executemany('INSERT INTO dependency_edges VALUES(?,?)',[(eid,x) for x in p.dependencies]);self._observe('commit.after_dependencies')
            for i,(bid,b) in enumerate(zip(block_ids,p.blocks)):
                c.execute('INSERT OR IGNORE INTO blocks VALUES(?,?,?,1,?)',(bid,len(b),'blocks/'+bid.hex(),'POSIX_FSYNC_CANDIDATE'))
                c.execute('INSERT INTO envelope_blocks VALUES(?,?,?)',(eid,bid,i))
            self._observe('commit.after_blocks')
            c.execute("INSERT INTO outbox VALUES(?,?,0,NULL,'pending')",(eid,p.operation_id));self._observe('commit.after_outbox')
            order=c.execute('SELECT coalesce(max(commit_order),0)+1 FROM local_commit_meta').fetchone()[0]
            c.execute('INSERT INTO local_commit_meta VALUES(?,?,?,?,?,?,?,?,?)',(p.operation_id,p.fingerprint,p.reservation_id,p.actor_generation,p.previous_envelope,p.encrypted_cache,self.generation,'POSIX_LOCAL_PROCESS_CRASH_CANDIDATE',order))
            self._observe('commit.after_meta')
            c.execute('UPDATE local_nonce_reservations SET consumed_by=? WHERE reservation_id=?',(eid,p.reservation_id));self._observe('commit.after_nonce')
            self._commit_authority_meta(p)
            self._observe('commit.before_commit');self._authorize_commit(p,fencing_token);attempted_commit=True;c.execute('COMMIT');self._observe('commit.after_commit')
            return self._lookup_operation(p.operation_id,p.input_digest)
        except BaseException as exc:
            rollback_failed=False
            if c.in_transaction:
                try:c.execute('ROLLBACK')
                except sqlite3.Error:rollback_failed=True
            if attempted_commit or rollback_failed:
                raise StoreError('LOCAL_OUTCOME_UNKNOWN',operation_id=p.operation_id,sqlite_code=getattr(exc,'sqlite_errorcode',None)) from None
            if isinstance(exc,StoreError):raise
            if isinstance(exc,sqlite3.Error):raise sqlite_error(exc,p.operation_id) from None
            if isinstance(exc,OSError):
                raise StoreError('STORAGE_FULL' if exc.errno==errno.ENOSPC else 'STORAGE_IO',operation_id=p.operation_id) from None
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            raise StoreError('LOCAL_ABORTED',operation_id=p.operation_id) from None
        finally:self._busy=False
    def pending(self,*,limit=128,after=None):
        self._alive()
        if self._busy or self.connection.in_transaction:raise StoreError('REENTRANT_OPERATION')
        if type(limit) is not int or not 1<=limit<=1024:raise StoreError('INVALID_INPUT')
        if after is not None:fixed(after,32)
        return [dict(x) for x in self.connection.execute('''SELECT o.envelope_id,o.operation_id,o.state,o.attempt_count,e.encrypted_bytes AS envelope
          FROM outbox o JOIN envelopes e USING(envelope_id) WHERE o.state='pending'
          AND (? IS NULL OR o.envelope_id>?) ORDER BY o.envelope_id LIMIT ?''',(after,after,limit))]
    def mark_inflight(self,eid):
        fixed(eid,32)
        def body():
            n=self.connection.execute("UPDATE outbox SET state='in-flight',attempt_count=attempt_count+1 WHERE envelope_id=? AND state='pending'",(eid,)).rowcount
            if n!=1:raise StoreError('OUTBOX_STATE')
        self._transaction(body)
    def recover_outbox(self):
        def body():return self.connection.execute("UPDATE outbox SET state='pending',next_attempt_local_ms=NULL WHERE state='in-flight'").rowcount
        return self._transaction(body)
    def advance_epoch(self,space_id,expected,new_epoch,control_head):
        fixed(space_id,32);fixed(control_head,32);u64(expected);u64(new_epoch)
        if new_epoch!=expected+1:raise StoreError('INVALID_INPUT')
        def body():
            c=self.connection
            row=c.execute('SELECT control_sequence FROM spaces WHERE space_id=? AND content_epoch=?',(space_id,u64(expected))).fetchone()
            if row is None:raise StoreError('EPOCH_MISMATCH')
            c.execute('UPDATE spaces SET content_epoch=?,control_head=?,control_sequence=? WHERE space_id=?',
                      (u64(new_epoch),control_head,u64(from_u64(row[0])+1),space_id))
            c.execute("UPDATE outbox SET state='rebase-required' WHERE state IN ('pending','in-flight') AND envelope_id IN (SELECT envelope_id FROM envelopes WHERE space_id=?)",(space_id,))
            c.execute('DELETE FROM actor_states WHERE space_id=?',(space_id,))
        self._transaction(body)
    def read_block(self,bid):self._alive();return self.block_port.read(bid)
    def audit(self):
        from .recovery import audit
        return audit(self)
    def collect_orphans(self):
        self._writable()
        if not self.audit()['valid']:raise StoreError('CORRUPT_STORE')
        referenced={r[0].hex() for r in self.connection.execute('SELECT block_id FROM blocks')}
        result={'blocks_removed':[],'staging_removed':[],'unrecognized':[]}
        for p in (self.root/'blocks').iterdir():
            safe(p)
            if not p.is_file() or re.fullmatch('[0-9a-f]{64}',p.name) is None:result['unrecognized'].append(p.name)
            elif p.name not in referenced:p.unlink();result['blocks_removed'].append(p.name)
        for p in (self.root/'staging').iterdir():
            safe(p)
            if p.is_file() and p.name.endswith('.part'):p.unlink();result['staging_removed'].append(p.name)
            else:result['unrecognized'].append('staging/'+p.name)
        sync_dir(self.root/'blocks');sync_dir(self.root/'staging');return result
    def export_snapshot(self,dest):
        from .recovery import export_snapshot
        return export_snapshot(self,Path(dest))

def restore_snapshot(source,dest,*,allow_unpatched_sqlite=False):
    from .recovery import restore_snapshot as restore
    return restore(Path(source),Path(dest),allow_unpatched_sqlite=allow_unpatched_sqlite)
