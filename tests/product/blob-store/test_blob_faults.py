from blob_support import *
import errno,os,subprocess,sys,signal
ROOT=Path(__file__).resolve().parents[3]
WRITE_STAGES=['crypto.after_content_reservation','crypto.after_content_seal','crypto.before_store_commit',
 'block.after_write','block.after_fsync','block.after_rename','block.after_dirsync',
 'commit.before_begin','commit.after_begin','commit.after_envelope','commit.after_ledger','commit.after_actor','commit.after_catalog','commit.after_dependencies','commit.after_blocks','commit.after_outbox','commit.after_meta','commit.after_nonce','commit.after_authority_proof','blob.after_manifest','blob.after_alias','blob.after_reference','blob.after_bindings','commit.before_commit','commit.after_commit']
MIGRATION_STAGES=['blob_migration.after_begin','blob_migration.after_schema','blob_migration.before_commit','blob_migration.after_commit']
QUEUE_STAGES=['incoming.after_data_write','incoming.after_data_fsync','incoming.before_ack_publish','incoming.after_ack_publish']
BACKUP_STAGES=['snapshot.after_db','snapshot.after_blocks','snapshot.after_manifest','snapshot.after_publish']
class BlobFaultTests(BlobTest):
    def child(self,action,stage,root=None,*extra):
        r=subprocess.run([sys.executable,'-I','-S',str(ROOT/'tests/product/blob-store/crash_worker.py'),str(root or self.root),action,stage,*map(str,extra)],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,-signal.SIGKILL,r.stdout+r.stderr);self.assertIn('REACHED:'+stage,r.stdout)
    def check_write(self,stage):
        self.start();self.close();self.child('write',stage);self.reopen();self.assertTrue(self.db.audit()['valid']);n=1 if stage=='commit.after_commit' else 0
        for table in ('commit_ledger','auth_commits','blob_commit_roots','blob_objects','blob_references'):self.assertEqual(self.count(table),n,(stage,table))
        self.activate();r=self.writer().write(*self.request(),attachments=(self.attachment(),));self.assertIsNotNone(r);self.assertTrue(self.db.audit()['valid']);self.assertEqual(self.count('commit_ledger'),1)
    def check_migration(self,stage):
        AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True).close();self.child('migration',stage)
        if stage.endswith('after_commit'):self.reopen();self.assertTrue(self.db.audit()['valid'])
        else:
            with AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True) as s:self.assertEqual(s._storage.connection.execute('PRAGMA user_version').fetchone()[0],2)
    def check_queue(self,stage):
        a=self.attachment();qroot=Path(self.tmp.name)/'incoming'
        with self.blob.IncomingQueue.create(qroot) as q:token=q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes))
        self.child('incoming',stage,qroot,token)
        with self.blob.IncomingQueue.open(qroot) as q:
            expected=len(a.sealed_bytes) if stage.endswith('after_ack_publish') else 0
            self.assertEqual(q.status(token)['acknowledged_bytes'],expected)
            if not expected:q.append(token,0,a.sealed_bytes)
            self.assertEqual(q.finish(token,self.p,self.s.secret,app=self.s.app,space=self.s.space,epoch=1),a)
    def check_backup(self,stage):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));self.close();snap=Path(self.tmp.name)/'snapshot';self.child('backup',stage,self.root,snap)
        self.assertEqual(snap.exists(),stage.endswith('after_publish'))
        if snap.exists():
            dest=Path(self.tmp.name)/'restored';self.blob.BlobStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True)
            with self.blob.BlobStore.open(dest,provider=self.p,allow_unpatched_sqlite=True) as d:self.assertTrue(d.audit()['valid'])
    def test_response_loss_keeps_exact_attachment_and_nonce(self):
        self.start();w=self.writer();a=(self.attachment(),)
        def hook(stage):
            if stage=='commit.after_commit':raise RuntimeError('reply lost')
        self.db.observer=hook;self.reject('LOCAL_OUTCOME_UNKNOWN',lambda:w.write(*self.request(),attachments=a));self.db.observer=None;n=self.count('issued_nonces');self.assertIsNotNone(w.read_committed(*self.request(),attachments=a));self.assertEqual(self.count('issued_nonces'),n)
    def test_file_fsync_failure_never_publishes_reference(self):
        self.start()
        def fail(fd):raise OSError(errno.ENOSPC,'injected full')
        self.db._storage.block_port.sync_file=fail;self.reject('STORAGE_FULL',lambda:self.writer().write(*self.request(),attachments=(self.attachment(),)));self.assertEqual(self.count('blob_references'),0);self.assertEqual(self.count('commit_ledger'),0)
    def test_sqlite_full_rolls_back_alias_and_reference(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));c=self.db._storage.connection;c.execute('PRAGMA wal_checkpoint(TRUNCATE)');pages=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(pages))
        # Use a valid large encrypted catalog row to force actual SQLITE_FULL, not a CHECK failure.
        def fill_valid(stage):
            if stage=='blob.after_alias':c.execute('UPDATE catalog SET encrypted_snapshot_ref=zeroblob(2000000)')
        self.db.observer=fill_valid;self.reject('SQLITE_FULL',lambda:self.db.commit(p));self.db.observer=None;self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('blob_objects'),0);self.assertTrue(self.db.audit()['valid'])
    def test_write_lock_conflict_has_no_reference(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));other=sqlite3.connect(self.root/'store.sqlite',isolation_level=None);self.addCleanup(other.close);other.execute('BEGIN IMMEDIATE');self.reject('SQLITE_BUSY',lambda:self.db.commit(p));other.execute('ROLLBACK');self.assertEqual(self.count('blob_references'),0);self.assertIsNotNone(self.db.commit(p))
    def test_files_left_after_db_abort_are_reported_not_deleted(self):
        self.start();a=self.attachment()
        def fail(stage):
            if stage=='blob.after_reference':raise RuntimeError('injected')
        self.db.observer=fail;self.reject('LOCAL_ABORTED',lambda:self.writer().write(*self.request(),attachments=(a,)));self.db.observer=None;report=self.db.orphan_report();self.assertEqual(len(report['unreferenced_locators']),1);self.assertFalse(report['deletion_performed'])
    def test_auth_change_after_file_publication_is_rechecked(self):
        self.start()
        def change(stage):
            if stage=='block.after_dirsync':self.db._storage.connection.execute("UPDATE auth_spaces SET phase='EPOCH_PENDING'")
        self.db.observer=change;self.reject(None,lambda:self.writer().write(*self.request(),attachments=(self.attachment(),)));self.assertEqual(self.count('blob_references'),0)

    def check_multi(self,stage):
        self.start();self.close();self.child('write_multi',stage);self.reopen();self.assertTrue(self.db.audit()['valid']);n=3 if stage=='commit.after_commit' else 0
        self.assertEqual(self.count('blob_references'),n);self.assertEqual(self.count('blob_objects'),n)
        self.activate();self.assertIsNotNone(self.writer().write(*self.request(),attachments=tuple(self.attachment(i) for i in range(3))))
    def check_discard(self,stage):
        a=self.attachment();qroot=Path(self.tmp.name)/'incoming'
        with self.blob.IncomingQueue.create(qroot) as q:token=q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes));q.append(token,0,a.sealed_bytes)
        self.child('discard',stage,qroot,token)
        with self.blob.IncomingQueue.open(qroot) as q:
            self.reject('TRANSFER_MISSING',lambda:q.status(token));self.assertFalse((qroot/(token+'.part')).exists())

def attach(prefix,stages,method):
    for stage in stages:
        def test(self,s=stage):getattr(self,method)(s)
        name='test_'+prefix+'_'+stage.replace('.','_').replace('#','_at_')
        test.__name__=name;setattr(BlobFaultTests,name,test)
attach('sigkill_write',WRITE_STAGES,'check_write')
attach('sigkill_migration',MIGRATION_STAGES,'check_migration')
attach('sigkill_queue',QUEUE_STAGES,'check_queue')
attach('sigkill_backup',BACKUP_STAGES,'check_backup')

MULTI_STAGES=['block.after_dirsync#2','blob.after_alias#2','blob.after_reference#2','commit.after_commit']
DISCARD_STAGES=['incoming.after_retire','incoming.after_discard']
attach('sigkill_multi',MULTI_STAGES,'check_multi')
attach('sigkill_discard',DISCARD_STAGES,'check_discard')
