from auth_store_support import *
from par_store.store import Store
class SchemaRestoreTests(AuthStoreTest):
    def test_v2_schema_has_separate_user_version(self):
        self.start();self.assertEqual(self.db._storage.connection.execute('PRAGMA user_version').fetchone()[0],2)
    def test_old_store_does_not_open_auth_schema(self):
        self.start();self.close();self.reject('SCHEMA_MISMATCH',lambda:Store.open(self.root,allow_unpatched_sqlite=True))
    def test_new_store_requires_explicit_migration(self):
        Store.create(self.root,allow_unpatched_sqlite=True).close();self.reject('SCHEMA_MISMATCH',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_empty_legacy_store_migrates_atomically(self):
        Store.create(self.root,allow_unpatched_sqlite=True).close();self.db=self.m.AuthorityStore.migrate_empty(self.root,provider=self.p,allow_unpatched_sqlite=True);self.db.enroll(self.s.app,self.s.space,self.s.genesis);self.assertTrue(self.db.audit()['valid'])
    def test_nonempty_legacy_is_not_silently_trusted(self):
        with Store.create(self.root,allow_unpatched_sqlite=True) as s:s.configure_space(self.s.space,self.s.app,1,h('head'))
        self.reject('LEGACY_DATA_REQUIRES_IMPORT',lambda:self.m.AuthorityStore.migrate_empty(self.root,provider=self.p,allow_unpatched_sqlite=True))
        with Store.open(self.root,allow_unpatched_sqlite=True) as s:self.assertEqual(s.connection.execute('SELECT count(*) FROM spaces').fetchone()[0],1)
    def test_migration_failure_rolls_back_schema(self):
        Store.create(self.root,allow_unpatched_sqlite=True).close()
        def fail(stage):
            if stage=='migration.after_schema':raise RuntimeError('injected')
        self.reject('AUTH_UPDATE_ABORTED',lambda:self.m.AuthorityStore.migrate_empty(self.root,provider=self.p,allow_unpatched_sqlite=True,observer=fail))
        with Store.open(self.root,allow_unpatched_sqlite=True) as s:self.assertEqual(s.connection.execute('PRAGMA user_version').fetchone()[0],1)
    def test_snapshot_restore_remains_readonly(self):
        self.start();r=self.writer().write(*self.request());snap=Path(self.tmp.name)/'snap';dest=Path(self.tmp.name)/'restored';self.db.export_snapshot(snap);self.m.AuthorityStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True);self.close();self.root=dest;self.db=self.m.AuthorityStore.open(dest,provider=self.p,allow_unpatched_sqlite=True);self.assertTrue(self.db.status(self.s.space)['restore_read_only']);self.assertEqual(self.writer().read_committed(*self.request()),r);self.reject('RESTORE_READ_ONLY',lambda:self.writer().write(*self.request(op=2)))
    def test_restore_does_not_forget_epoch_key_history(self):
        self.start();snap=Path(self.tmp.name)/'snap';dest=Path(self.tmp.name)/'restored';self.db.export_snapshot(snap);self.m.AuthorityStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True);self.close();self.root=dest;self.db=self.m.AuthorityStore.open(dest,provider=self.p,allow_unpatched_sqlite=True);self.assertEqual(self.count('auth_epoch_keys'),1);self.reject('RESTORE_READ_ONLY',lambda:self.activate())
    def test_extra_trigger_rejected_at_open(self):
        self.start();self.db._storage.connection.execute('CREATE TRIGGER bad AFTER INSERT ON auth_commits BEGIN SELECT 1; END');self.close();self.reject('SCHEMA_MISMATCH',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_update_failure_leaves_memory_and_db_consistent(self):
        self.start();before=self.db.pin(self.s.space)
        def fail(stage):
            if stage=='auth.after_row':raise RuntimeError('injected')
        self.db.observer=fail;self.reject('AUTH_UPDATE_ABORTED',lambda:self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw']))));self.db.observer=None;self.assertEqual(self.db.pin(self.s.space),before);self.assertEqual(self.db.status(self.s.space)['state'],'AUTH_PERSISTENCE_UNCERTAIN')
    def test_update_response_loss_makes_outcome_unknown(self):
        self.start()
        def fail(stage):
            if stage=='auth.after_commit':raise RuntimeError('injected')
        self.db.observer=fail;self.reject('AUTH_OUTCOME_UNKNOWN',lambda:self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw']))));self.db.observer=None;self.assertEqual(self.db.status(self.s.space)['durable_phase'],'MEMBERSHIP_PENDING')
    def test_invalid_authority_snapshot_never_publishes_destination(self):
        from par_store.recovery import file_hash
        self.start();snap=Path(self.tmp.name)/'snap';dest=Path(self.tmp.name)/'bad-restored';self.db.export_snapshot(snap)
        c=sqlite3.connect(snap/'store.sqlite');c.execute('UPDATE auth_spaces SET head=?',(h('forged'),));c.commit();c.close()
        mf=snap/'SNAPSHOT.json';m=json.loads(mf.read_text())
        for f in m['files']:
            if f['path']=='store.sqlite':f['sha256']=file_hash(snap/'store.sqlite');f['size']=(snap/'store.sqlite').stat().st_size
        mf.write_text(json.dumps(m))
        self.reject(None,lambda:self.m.AuthorityStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True));self.assertFalse(dest.exists(),'unverified authority database was published')
