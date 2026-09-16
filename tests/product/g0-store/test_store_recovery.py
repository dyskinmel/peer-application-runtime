from store_helpers import *
import os

class RecoveryTests(StoreCase):
    def snapshot(self):
        p=self.prepare(blocks=(b'sealed-one',));self.commit(p)
        dest=Path(self.tmp.name)/'snapshot';manifest=self.s.export_snapshot(dest)
        return p,dest,manifest
    def test_consistent_snapshot_and_restore(self):
        p,snap,m=self.snapshot();dest=Path(self.tmp.name)/'restored'
        self.api.restore_snapshot(snap,dest,allow_unpatched_sqlite=True)
        with self.api.Store.open(dest,allow_unpatched_sqlite=True) as restored:
            self.assertEqual(restored.lookup_operation(p.operation_id,p.input_digest),self.s.lookup_operation(p.operation_id,p.input_digest))
            self.assertTrue(restored.audit()['valid'])
            self.assertEqual(restored.read_block(hashlib.sha256(b'sealed-one').digest()),b'sealed-one')
    def test_restored_writer_cannot_reuse_stale_nonce_history(self):
        p,snap,m=self.snapshot();dest=Path(self.tmp.name)/'restored';self.api.restore_snapshot(snap,dest,allow_unpatched_sqlite=True)
        with self.api.Store.open(dest,allow_unpatched_sqlite=True) as restored:
            self.err('RESTORE_READ_ONLY',restored.reserve_nonce,b'n'*16,h('new'),KEY,b'n'*24)
            self.err('RESTORE_READ_ONLY',restored.commit,p,fencing_token=restored.fencing_token)
    def test_snapshot_excludes_later_writes(self):
        p,snap,m=self.snapshot();self.commit(self.prepare(2,sequence=2,previous=p.envelope_id,blocks=(b'sealed-two',)))
        dest=Path(self.tmp.name)/'restored';self.api.restore_snapshot(snap,dest,allow_unpatched_sqlite=True)
        with self.api.Store.open(dest,allow_unpatched_sqlite=True) as restored:
            self.assertIsNone(restored.lookup_operation((2).to_bytes(16,'big'),h('input-2')))
            self.assertEqual(len(restored.pending()),1)
    def test_snapshot_is_self_contained_without_wal(self):
        _,snap,m=self.snapshot();self.assertFalse((snap/'store.sqlite-wal').exists())
        with sqlite3.connect('file:'+str(snap/'store.sqlite')+'?mode=ro',uri=True) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('SELECT count(*) FROM commit_ledger').fetchone()[0],1)
    def test_export_refuses_existing_destination(self):
        _,snap,_=self.snapshot();self.err('DESTINATION_EXISTS',self.s.export_snapshot,snap)
    def test_restore_refuses_existing_destination(self):
        _,snap,_=self.snapshot();self.err('DESTINATION_EXISTS',self.api.restore_snapshot,snap,self.root,allow_unpatched_sqlite=True)
    def test_corrupted_snapshot_block_rejected(self):
        _,snap,_=self.snapshot();next((snap/'blocks').iterdir()).write_bytes(b'bad')
        dest=Path(self.tmp.name)/'restored';self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,dest,allow_unpatched_sqlite=True)
        self.assertFalse(dest.exists())
    def test_corrupted_snapshot_db_rejected(self):
        _,snap,_=self.snapshot();(snap/'store.sqlite').write_bytes(b'bad')
        dest=Path(self.tmp.name)/'restored';self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,dest,allow_unpatched_sqlite=True)
        self.assertFalse(dest.exists())
    def test_extra_snapshot_file_rejected(self):
        _,snap,_=self.snapshot();(snap/'extra').write_bytes(b'bad')
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
    def test_missing_manifest_rejected(self):
        _,snap,_=self.snapshot();(snap/'SNAPSHOT.json').unlink()
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
    def test_duplicate_manifest_keys_rejected(self):
        _,snap,_=self.snapshot();(snap/'SNAPSHOT.json').write_text('{"schema_version":1,"schema_version":1}')
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
    def test_manifest_path_traversal_rejected(self):
        _,snap,m=self.snapshot();m['files'][0]['path']='../outside';(snap/'SNAPSHOT.json').write_text(json.dumps(m))
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
    def test_snapshot_symlink_rejected(self):
        _,snap,_=self.snapshot();p=next((snap/'blocks').iterdir());p.unlink();p.symlink_to(self.root/'store.sqlite')
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
    def test_export_refuses_corrupt_source_without_modifying_it(self):
        p=self.prepare(blocks=(b'sealed',));self.commit(p)
        path=self.root/'blocks'/hashlib.sha256(b'sealed').hexdigest();path.write_bytes(b'bad')
        self.err('CORRUPT_STORE',self.s.export_snapshot,Path(self.tmp.name)/'snapshot')
        self.assertEqual(path.read_bytes(),b'bad')
    def test_restore_does_not_modify_source_snapshot(self):
        _,snap,_=self.snapshot();before={str(p.relative_to(snap)):h(p.read_bytes()) for p in snap.rglob('*') if p.is_file()}
        self.api.restore_snapshot(snap,Path(self.tmp.name)/'r',allow_unpatched_sqlite=True)
        after={str(p.relative_to(snap)):h(p.read_bytes()) for p in snap.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
    def test_incomplete_export_not_published_as_complete(self):
        self.commit(self.prepare(blocks=(b'sealed',)));dest=Path(self.tmp.name)/'snapshot'
        self.s.observer=lambda stage: (_ for _ in ()).throw(RuntimeError('cut')) if stage=='snapshot.after_db' else None
        self.err('SNAPSHOT_FAILED',self.s.export_snapshot,dest);self.assertFalse(dest.exists());self.assertTrue(self.s.audit()['valid'])
    def test_orphan_files_are_not_exported(self):
        (self.root/'blocks'/h('orphan').hex()).write_bytes(b'orphan')
        _,snap,m=self.snapshot();self.assertNotIn('blocks/'+h('orphan').hex(),{x['path'] for x in m['files']})

class SnapshotReviewTests(StoreCase):
    def test_snapshot_rejects_broken_schema_even_with_recomputed_file_hash(self):
        self.commit(self.prepare());dest=Path(self.tmp.name)/'snap';m=self.s.export_snapshot(dest)
        db=dest/'store.sqlite';c=sqlite3.connect(db);c.execute('CREATE TABLE attacker(x BLOB)');c.commit();c.close()
        entry=next(e for e in m['files'] if e['path']=='store.sqlite');entry.update(size=db.stat().st_size,sha256=hashlib.sha256(db.read_bytes()).hexdigest())
        (dest/'SNAPSHOT.json').write_text(json.dumps(m))
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,dest,Path(self.tmp.name)/'restored',allow_unpatched_sqlite=True)
    def test_snapshot_malformed_digest_types_rejected(self):
        self.commit(self.prepare());snap=Path(self.tmp.name)/'snap';m=self.s.export_snapshot(snap)
        m['files'][0]['size']=True;(snap/'SNAPSHOT.json').write_text(json.dumps(m))
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'restored',allow_unpatched_sqlite=True)
    def test_unknown_snapshot_profile_rejected(self):
        self.commit(self.prepare());snap=Path(self.tmp.name)/'snap';m=self.s.export_snapshot(snap)
        m['profile_digest']='00'*32;(snap/'SNAPSHOT.json').write_text(json.dumps(m))
        self.err('SNAPSHOT_INVALID',self.api.restore_snapshot,snap,Path(self.tmp.name)/'restored',allow_unpatched_sqlite=True)

class PublicationOutcomeTests(StoreCase):
    def test_export_failure_after_publish_is_outcome_unknown(self):
        self.commit(self.prepare(blocks=(b'sealed',)));dest=Path(self.tmp.name)/'snapshot'
        def observer(stage):
            if stage=='snapshot.after_publish':raise RuntimeError('caller lost')
        self.s.observer=observer
        self.err('SNAPSHOT_OUTCOME_UNKNOWN',self.s.export_snapshot,dest)
        self.s.observer=None
        recovery=importlib.import_module('par_store.recovery')
        self.assertEqual(recovery.validate_snapshot(dest)['kind'],'LOCAL_STORE_SNAPSHOT')
    def test_restore_parent_sync_failure_is_outcome_unknown(self):
        from unittest.mock import patch
        self.commit(self.prepare());snap=Path(self.tmp.name)/'snap';self.s.export_snapshot(snap)
        recovery=importlib.import_module('par_store.recovery');original=recovery.sync_dir
        dest=Path(self.tmp.name)/'restored'
        def fail_only_parent(path):
            if path==dest.parent:raise OSError('parent sync failed')
            return original(path)
        with patch.object(recovery,'sync_dir',side_effect=fail_only_parent):
            self.err('SNAPSHOT_OUTCOME_UNKNOWN',self.api.restore_snapshot,snap,dest,allow_unpatched_sqlite=True)
        self.assertTrue(dest.is_dir())
        with self.api.Store.open(dest,allow_unpatched_sqlite=True) as restored:
            self.assertTrue(restored.audit()['valid']);self.assertTrue(restored.restore_read_only)

class BackupResourceTests(StoreCase):
    def test_failed_backup_configuration_closes_real_target_connection(self):
        from unittest.mock import patch
        recovery=importlib.import_module('par_store.recovery')
        real_connect=sqlite3.connect;targets=[]
        class FailingTarget(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql=='PRAGMA journal_mode=DELETE':
                    raise sqlite3.OperationalError('injected target configuration failure')
                return super().execute(sql,*args,**kwargs)
        def connect(*args,**kwargs):
            if str(args[0])==':memory:':return real_connect(*args,**kwargs)
            connection=real_connect(*args,**kwargs,factory=FailingTarget)
            targets.append(connection);return connection
        self.commit(self.prepare())
        try:
            with patch.object(recovery.sqlite3,'connect',side_effect=connect):
                self.err('SNAPSHOT_FAILED',self.s.export_snapshot,Path(self.tmp.name)/'snapshot')
            self.assertEqual(len(targets),1)
            with self.assertRaises(sqlite3.ProgrammingError):
                targets[0].execute('SELECT 1')
            self.assertTrue(self.s.audit()['valid'])
        finally:
            for connection in targets:connection.close()
