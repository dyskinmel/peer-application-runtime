from blob_support import *
class BlobRecoveryTests(BlobTest):
    def test_schema3_explicit(self):
        self.start();self.assertEqual(self.db._storage.connection.execute('PRAGMA user_version').fetchone()[0],3)
    def test_schema2_does_not_open_schema3(self):
        self.start();self.close();self.reject('SCHEMA_MISMATCH',lambda:AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_schema3_requires_explicit_migration(self):
        AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True).close();self.reject('SCHEMA_MISMATCH',lambda:self.blob.BlobStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_populated_v2_without_blobs_migrates_without_data_loss(self):
        self.db=AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True);self.db.enroll(self.s.app,self.s.space,self.s.genesis);self.db.observe(self.s.space,self.b['raw']);self.db.provide_membership(self.s.space,self.b['pages']);self.activate();r=self.legacy_writer().write(*self.request());self.close()
        self.db=self.blob.BlobStore.migrate_v2(self.root,provider=self.p,allow_unpatched_sqlite=True);self.assertTrue(self.db.audit()['valid']);self.assertEqual(self.legacy_writer().read_committed(*self.request()),r);self.assertEqual(self.count('blob_commit_roots'),1)
    def test_migration_failure_leaves_schema2(self):
        AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True).close()
        def hook(stage):
            if stage=='blob_migration.after_schema':raise RuntimeError('injected')
        self.reject('MIGRATION_ABORTED',lambda:self.blob.BlobStore.migrate_v2(self.root,provider=self.p,allow_unpatched_sqlite=True,observer=hook))
        with AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True) as d:self.assertEqual(d._storage.connection.execute('PRAGMA user_version').fetchone()[0],2)
    def test_empty_v2_migration_response_loss_is_queryable(self):
        AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True).close()
        def hook(stage):
            if stage=='blob_migration.after_commit':raise RuntimeError('injected')
        self.reject('MIGRATION_OUTCOME_UNKNOWN',lambda:self.blob.BlobStore.migrate_v2(self.root,provider=self.p,allow_unpatched_sqlite=True,observer=hook));self.reopen();self.assertTrue(self.db.audit()['valid'])
    def test_reopen_requires_reactivation_but_readable(self):
        self.start();a=(self.attachment(),);r=self.writer().write(*self.request(),attachments=a);self.reopen();self.assertEqual(self.db.status(self.s.space)['state'],'EPOCH_PENDING');self.assertEqual(self.db.read_attachment(r.envelope_id,0,self.s.secret),b'synthetic attachment');self.assertEqual(self.writer().read_committed(*self.request(),attachments=a),r)
    def test_reopen_old_ticket_is_rejected(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));self.reopen();self.activate();self.reject('CANDIDATE_INVALID',lambda:self.db.commit(p))
    def test_backup_restore_signed_attachments_readonly(self):
        self.start();a=(self.attachment(),);r=self.writer().write(*self.request(),attachments=a);snap=Path(self.tmp.name)/'snapshot';dest=Path(self.tmp.name)/'restored';self.db.export_snapshot(snap);self.blob.BlobStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True);self.close();self.root=dest;self.reopen();self.assertEqual(self.db.read_attachment(r.envelope_id,0,self.s.secret),b'synthetic attachment');self.assertEqual(self.writer().read_committed(*self.request(),attachments=a),r);self.reject('RESTORE_READ_ONLY',lambda:self.writer().write(*self.request(op=2)))
    def test_missing_block_rejected_on_reopen(self):
        self.start();a=self.attachment();self.writer().write(*self.request(),attachments=(a,));(self.root/'blocks'/hashlib.sha256(a.sealed_bytes).hexdigest()).unlink();self.close();self.reject('BLOB_STORE_CORRUPT',self.reopen)
    def test_corrupt_block_rejected_on_read(self):
        self.start();a=self.attachment();r=self.writer().write(*self.request(),attachments=(a,));(self.root/'blocks'/hashlib.sha256(a.sealed_bytes).hexdigest()).write_bytes(b'bad');self.reject('BLOB_STORE_CORRUPT',lambda:self.db.read_attachment(r.envelope_id,0,self.s.secret))
    def test_alias_metadata_tamper_rejected(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));self.db._storage.connection.execute('UPDATE blob_objects SET chunk_index=?',((2).to_bytes(8,'big'),));self.assertFalse(self.db.audit()['valid'])
    def test_deleted_reference_not_silently_empty(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));self.db._storage.connection.execute('DELETE FROM blob_references');self.assertFalse(self.db.audit()['valid'])
    def test_reference_position_change_is_detected(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));self.db._storage.connection.execute('UPDATE blob_references SET position=5');self.assertFalse(self.db.audit()['valid'])
    def test_signed_manifest_tamper_rejected(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));c=self.db._storage.connection;o=decode(c.execute('SELECT manifest FROM blob_commit_roots').fetchone()[0]);o[1]=b'x'*64;c.execute('UPDATE blob_commit_roots SET manifest=?',(encode(o),));self.assertFalse(self.db.audit()['valid'])
    def test_other_author_signature_is_rejected(self):
        from par_crypto.primitives import domain
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));c=self.db._storage.connection;o=decode(c.execute('SELECT manifest FROM blob_commit_roots').fetchone()[0]);o[1]=self.p.sign(self.s.devices[1]['seed'],domain('blob-store-local/attachment-sign',[o[0]]));c.execute('UPDATE blob_commit_roots SET manifest=?',(encode(o),));self.assertFalse(self.db.audit()['valid'])
    def test_removed_manifest_with_recomputed_snapshot_hash_not_published(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));snap=Path(self.tmp.name)/'snapshot';dest=Path(self.tmp.name)/'restore';self.db.export_snapshot(snap);c=sqlite3.connect(snap/'store.sqlite');c.execute('DELETE FROM blob_commit_roots');c.commit();c.close();self.rehash_snapshot(snap);self.reject(None,lambda:self.blob.BlobStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True));self.assertFalse(dest.exists())
    def test_invalid_signature_in_rehashed_backup_not_published(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));snap=Path(self.tmp.name)/'snapshot';dest=Path(self.tmp.name)/'restore';self.db.export_snapshot(snap);c=sqlite3.connect(snap/'store.sqlite');c.execute('UPDATE blob_commit_roots SET manifest=?',(b'bad',));c.commit();c.close();self.rehash_snapshot(snap);self.reject(None,lambda:self.blob.BlobStore.restore_snapshot(snap,dest,provider=self.p,allow_unpatched_sqlite=True));self.assertFalse(dest.exists())
    def test_reordered_refs_and_file_links_cannot_bypass_signature(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),self.attachment(1)));c=self.db._storage.connection
        for table in ('envelope_blocks','blob_references'):
            c.execute('UPDATE '+table+' SET position=120 WHERE position=0');c.execute('UPDATE '+table+' SET position=0 WHERE position=1');c.execute('UPDATE '+table+' SET position=1 WHERE position=120')
        self.assertFalse(self.db.audit()['valid'])
    def test_symlinked_block_rejected(self):
        self.start();a=self.attachment();self.writer().write(*self.request(),attachments=(a,));path=self.root/'blocks'/hashlib.sha256(a.sealed_bytes).hexdigest();dest=Path(self.tmp.name)/'elsewhere';path.rename(dest);path.symlink_to(dest);self.assertFalse(self.db.audit()['valid'])
    def test_extra_schema_trigger_rejected(self):
        self.start();self.db._storage.connection.execute('CREATE TRIGGER altered AFTER INSERT ON blob_objects BEGIN SELECT 1; END');self.close();self.reject('SCHEMA_MISMATCH',self.reopen)
    def test_unknown_envelope_does_not_mean_empty_attachments(self):
        self.start();self.reject('COMMIT_NOT_FOUND',lambda:self.db.attachments(h('unknown')))
    def test_invalid_position_rejected(self):
        self.start();r=self.writer().write(*self.request(),attachments=(self.attachment(),));self.reject('BLOB_INPUT',lambda:self.db.read_attachment(r.envelope_id,True,self.s.secret));self.reject('ATTACHMENT_NOT_FOUND',lambda:self.db.read_attachment(r.envelope_id,1,self.s.secret))
