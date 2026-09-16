"""Snapshot, fail-closed audit and read-only restore. Hash manifests are NOT signatures."""
from __future__ import annotations
import hashlib,json,os,re,shutil,sqlite3,tempfile,time
from pathlib import Path
from .errors import StoreError
from .model import PreparedCommit,from_u64,sha,require_sqlite
from .fs import safe,sync_dir,regular

MAX_FILES=4097
MAX_DB_BYTES=268435456
MAX_SNAPSHOT_BYTES=1073741824

def file_hash(path):
    regular(path);h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    return h.hexdigest()

def copy_file(src,dest):
    regular(src);safe(dest)
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with src.open('rb') as f,os.fdopen(fd,'wb') as out:
        shutil.copyfileobj(f,out,65536);out.flush();os.fsync(out.fileno())

def audit(store):
    store._alive();c=store.connection;errors=[]
    if c.in_transaction:return {'valid':False,'errors':['AUDIT_DURING_TRANSACTION']}
    try:
        c.execute('BEGIN')
        if not store.schema_matches(c):errors.append('SCHEMA_MISMATCH')
        if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':errors.append('SQLITE_INTEGRITY')
        if list(c.execute('PRAGMA foreign_key_check')):errors.append('FOREIGN_KEYS')
        envs=list(c.execute('SELECT * FROM envelopes'))
        for table in ('commit_ledger','local_commit_meta','outbox'):
            if c.execute('SELECT count(*) FROM '+table).fetchone()[0]!=len(envs):errors.append('COUNT_'+table)
        for e in envs:
            eid=e['envelope_id']
            row=c.execute('SELECT * FROM commit_ledger WHERE commit_id=?',(eid,)).fetchone()
            if row is None:errors.append('LEDGER_MISSING');continue
            m=c.execute('SELECT * FROM local_commit_meta WHERE operation_id=?',(row['operation_id'],)).fetchone()
            outbox=c.execute('SELECT operation_id FROM outbox WHERE envelope_id=?',(eid,)).fetchone()
            if m is None or outbox is None or outbox[0]!=row['operation_id']:errors.append('ATOMIC_SET_MISSING');continue
            nr=c.execute('SELECT * FROM local_nonce_reservations WHERE reservation_id=?',(m['reservation_id'],)).fetchone()
            if nr is None or nr['consumed_by']!=eid or nr['operation_id']!=row['operation_id']:errors.append('NONCE_BINDING')
            intent=c.execute('SELECT input_digest FROM local_operation_intents WHERE operation_id=?',(row['operation_id'],)).fetchone()
            if intent is None or intent[0]!=row['input_digest']:errors.append('INTENT_BINDING')
            if nr is not None:
                issued=c.execute('SELECT payload_digest FROM issued_nonces WHERE key_context=? AND nonce=?',(nr['key_context'],nr['nonce'])).fetchone()
                if issued is None or issued[0]!=row['input_digest']:errors.append('NONCE_INPUT_BINDING')
            if row['space_id']!=e['space_id']:errors.append('SPACE_BINDING')
            deps=tuple(x[0] for x in c.execute('SELECT required_change_hash FROM dependency_edges WHERE envelope_id=? ORDER BY required_change_hash',(eid,)))
            blocks=[]
            for x in c.execute('SELECT block_id FROM envelope_blocks WHERE envelope_id=? ORDER BY position',(eid,)):
                try:blocks.append(store.read_block(x[0]))
                except StoreError as exc:errors.append(exc.code)
            p=PreparedCommit(row['operation_id'],row['input_digest'],e['space_id'],e['object_id'],e['actor_id'],m['actor_generation'],
                             from_u64(e['epoch']),from_u64(e['sequence']),m['previous_envelope'],e['change_hash'],m['reservation_id'],
                             e['encrypted_bytes'],m['encrypted_cache'],row['receipt_encrypted'],deps,tuple(blocks))
            try:
                p.validate()
                if p.envelope_id!=eid:errors.append('ENVELOPE_HASH')
                if p.fingerprint!=m['prepared_digest']:errors.append('PREPARED_HASH')
            except StoreError as exc:errors.append(exc.code)
        for b in c.execute('SELECT * FROM blocks'):
            if b['relative_object_path']!='blocks/'+b['block_id'].hex() or b['published']!=1:errors.append('BLOCK_PATH');continue
            try:
                if len(store.read_block(b['block_id']))!=b['size_bytes']:errors.append('BLOCK_SIZE')
            except StoreError as exc:errors.append(exc.code)
        expected_actors={};expected_catalog={}
        # Derive expected live state from commits, never merely check rows that happen to remain.
        for r in c.execute('''SELECT e.*,m.actor_generation,m.encrypted_cache,m.commit_order,s.content_epoch
          FROM envelopes e JOIN commit_ledger l ON l.commit_id=e.envelope_id
          JOIN local_commit_meta m USING(operation_id) JOIN spaces s ON s.space_id=e.space_id ORDER BY m.commit_order'''):
            expected_catalog[(r['space_id'],r['object_id'])]=r['encrypted_cache']
            if r['epoch']==r['content_epoch']:
                expected_actors[(r['space_id'],r['object_id'],r['actor_id'])]=(r['actor_generation'],r['sequence'],r['envelope_id'])
        actual_actors={(a['space_id'],a['object_id'],a['actor_id']):(a['generation'],a['last_sequence'],a['previous_envelope']) for a in c.execute('SELECT * FROM actor_states')}
        if actual_actors!=expected_actors:errors.append('ACTOR_STATE')
        actual_catalog={(a['space_id'],a['object_id']):a['encrypted_snapshot_ref'] for a in c.execute('SELECT * FROM catalog')}
        if actual_catalog!=expected_catalog:errors.append('CACHE_REFERENCE')
    except (sqlite3.Error,StoreError,ValueError,TypeError,KeyError):errors.append('CORRUPT_STORE')
    finally:
        if c.in_transaction:c.execute('ROLLBACK')
    return {'valid':not errors,'errors':sorted(set(errors)),'scope':'LOCAL_STRUCTURAL_HASH_AUDIT_NO_AUTHENTICATION'}

def export_snapshot(store,dest):
    store._alive();dest=safe(dest)
    if dest.exists():raise StoreError('DESTINATION_EXISTS')
    if dest==store.root or dest.is_relative_to(store.root):raise StoreError('UNSAFE_PATH')
    if store._busy:raise StoreError('REENTRANT_OPERATION')
    if not store.audit()['valid']:raise StoreError('CORRUPT_STORE')
    dest.parent.mkdir(parents=True,exist_ok=True);safe(dest.parent)
    stage=Path(tempfile.mkdtemp(prefix='.'+dest.name+'.pending-',dir=dest.parent));published=False
    store._busy=True
    try:
        (stage/'blocks').mkdir(mode=0o700)
        db=stage/'store.sqlite';deadline=time.monotonic()+15
        def progress(status,remaining,total):
            if time.monotonic()>deadline:raise StoreError('SNAPSHOT_TIMEOUT')
        target=sqlite3.connect(db,isolation_level=None)
        try:
            store.connection.backup(target,pages=256,progress=progress,sleep=0.01)
            target.execute('PRAGMA journal_mode=DELETE');target.execute('PRAGMA synchronous=FULL')
        finally:
            # Also close after backup/configuration failure, not only on success.
            target.close()
        os.chmod(db,0o600)
        fd=os.open(db,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        store._observe('snapshot.after_db')
        paths=['store.sqlite']
        for b in store.connection.execute('SELECT * FROM blocks ORDER BY block_id'):
            store.read_block(b['block_id'])
            rel='blocks/'+b['block_id'].hex();copy_file(store.root/rel,stage/rel);paths.append(rel)
        store._observe('snapshot.after_blocks')
        if len(paths)>MAX_FILES:raise StoreError('SNAPSHOT_LIMIT')
        entries=[{'path':rel,'size':(stage/rel).stat().st_size,'sha256':file_hash(stage/rel)} for rel in paths]
        if entries[0]['size']>MAX_DB_BYTES or sum(x['size'] for x in entries)>MAX_SNAPSHOT_BYTES:raise StoreError('SNAPSHOT_LIMIT')
        m={'schema_version':1,'kind':'LOCAL_STORE_SNAPSHOT','profile_digest':store.schema_profile().hex(),
           'authenticated':False,'write_activation':'REKEY_REQUIRED_READ_ONLY_RESTORE','files':entries}
        with (stage/'SNAPSHOT.json').open('x',encoding='utf-8') as f:
            json.dump(m,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        store._observe('snapshot.after_manifest');sync_dir(stage/'blocks');sync_dir(stage)
        if dest.exists():raise StoreError('DESTINATION_EXISTS')
        os.rename(stage,dest);published=True;store._observe('snapshot.after_publish');sync_dir(dest.parent);return m
    except BaseException as exc:
        if published:raise StoreError('SNAPSHOT_OUTCOME_UNKNOWN') from None
        if isinstance(exc,StoreError):raise
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        raise StoreError('SNAPSHOT_FAILED') from None
    finally:
        store._busy=False
        if not published and stage.exists():shutil.rmtree(stage)

def strict_pairs(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:raise ValueError('duplicate key')
        obj[k]=v
    return obj

def validate_snapshot(source,*,store_type=None):
    from .store import Store
    store_type=store_type or Store
    try:
        source=safe(source)
        for p in source.rglob('*'):safe(p)
        file=source/'SNAPSHOT.json';regular(file)
        if file.stat().st_size>4194304:raise ValueError()
        m=json.loads(file.read_text('utf-8'),object_pairs_hook=strict_pairs)
        if set(m)!= {'schema_version','kind','profile_digest','authenticated','write_activation','files'}:raise ValueError()
        if type(m['schema_version']) is not int or m['schema_version']!=1 or m['kind']!='LOCAL_STORE_SNAPSHOT':raise ValueError()
        if m['profile_digest']!=store_type.schema_profile().hex() or m['authenticated'] is not False or m['write_activation']!='REKEY_REQUIRED_READ_ONLY_RESTORE':raise ValueError()
        rows=m['files']
        if type(rows) is not list or not 1<=len(rows)<=MAX_FILES:raise ValueError()
        listed=set();total=0
        for e in rows:
            if set(e)!= {'path','size','sha256'}:raise ValueError()
            rel=e['path']
            if type(rel) is not str or (rel!='store.sqlite' and re.fullmatch(r'blocks/[0-9a-f]{64}',rel) is None):raise ValueError()
            if rel in listed:raise ValueError()
            if type(e['size']) is not int or e['size']<0 or type(e['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',e['sha256']) is None:raise ValueError()
            total+=e['size'];listed.add(rel);p=safe(source/rel);regular(p)
            if p.stat().st_size!=e['size'] or file_hash(p)!=e['sha256']:raise ValueError()
        if 'store.sqlite' not in listed or (source/'store.sqlite').stat().st_size>MAX_DB_BYTES or total>MAX_SNAPSHOT_BYTES:raise ValueError()
        actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
        if actual!=listed|{'SNAPSHOT.json'}:raise ValueError()
        if any(p.is_dir() and p.relative_to(source).as_posix()!='blocks' for p in source.rglob('*')):raise ValueError()
        return m
    except (OSError,ValueError,TypeError,KeyError,StoreError):raise StoreError('SNAPSHOT_INVALID') from None

def restore_snapshot(source,dest,*,allow_unpatched_sqlite=False,store_type=None,stage_validator=None):
    from .store import Store
    store_type=store_type or Store
    require_sqlite(sqlite3.sqlite_version,allow_unpatched_sqlite)
    dest=safe(dest)
    if dest.exists():raise StoreError('DESTINATION_EXISTS')
    source=safe(source)
    if dest.is_relative_to(source):raise StoreError('UNSAFE_PATH')
    m=validate_snapshot(source,store_type=store_type)
    dest.parent.mkdir(parents=True,exist_ok=True);safe(dest.parent)
    stage=Path(tempfile.mkdtemp(prefix='.'+dest.name+'.restoring-',dir=dest.parent));published=False
    try:
        (stage/'blocks').mkdir(mode=0o700)
        for e in m['files']:
            copy_file(source/e['path'],stage/e['path'])
            if file_hash(stage/e['path'])!=e['sha256']:raise StoreError('SNAPSHOT_INVALID')
        db=stage/'store.sqlite';c=sqlite3.connect(db,isolation_level=None)
        try:
            if not store_type.schema_matches(c):raise StoreError('SNAPSHOT_INVALID')
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise StoreError('SNAPSHOT_INVALID')
            c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE')
            n=c.execute('UPDATE local_settings SET read_only_restore=1 WHERE singleton=1').rowcount
            if n!=1:raise StoreError('SNAPSHOT_INVALID')
            c.execute('COMMIT')
        finally:c.close()
        with store_type.open(stage,allow_unpatched_sqlite=allow_unpatched_sqlite) as s:
            if not s.audit()['valid']:raise StoreError('SNAPSHOT_INVALID')
        if stage_validator is not None:stage_validator(stage)
        provenance={'schema_version':1,'snapshot_manifest_sha256':file_hash(source/'SNAPSHOT.json'),
                    'kind':'READ_ONLY_RESTORE','cryptography_verified':False,'new_write_keys_required':True}
        with (stage/'RESTORE.json').open('x',encoding='utf-8') as f:
            json.dump(provenance,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        sync_dir(stage/'blocks');sync_dir(stage)
        if dest.exists():raise StoreError('DESTINATION_EXISTS')
        os.rename(stage,dest);published=True;sync_dir(dest.parent);return provenance
    except BaseException as exc:
        if published:raise StoreError('SNAPSHOT_OUTCOME_UNKNOWN') from None
        if isinstance(exc,StoreError):raise
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        raise StoreError('SNAPSHOT_INVALID') from None
    finally:
        if not published and stage.exists():shutil.rmtree(stage)
