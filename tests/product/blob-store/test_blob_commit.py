from blob_support import *
class BlobCommitTests(BlobTest):
    def test_atomic_attachments_and_authority(self):
        self.start();a=self.attachment();r=self.writer().write(*self.request(),attachments=(a,));self.assertEqual(self.count('blob_objects'),1);self.assertEqual(self.count('blob_references'),1);self.assertEqual(self.count('auth_commits'),1);self.assertTrue(self.db.audit()['valid']);self.assertEqual(self.db.attachments(r.envelope_id)[0].typed_id,a.typed_id)
    def test_decrypt_committed_attachment(self):
        self.start();a=self.attachment();r=self.writer().write(*self.request(),attachments=(a,));self.assertEqual(self.db.read_attachment(r.envelope_id,0,self.s.secret),b'synthetic attachment')
    def test_wrong_read_key_rejected(self):
        self.start();r=self.writer().write(*self.request(),attachments=(self.attachment(),));self.reject('AEAD_INVALID',lambda:self.db.read_attachment(r.envelope_id,0,h('wrong')))
    def test_document_remains_pending(self):
        self.start();self.writer().write(*self.request(),attachments=(self.attachment(),));self.assertEqual(self.db._storage.connection.execute('SELECT state FROM envelopes').fetchone()[0],'pending')
    def test_no_plaintext_in_database(self):
        self.start();a=self.attachment(plain=b'sensitive unique attachment contents');self.writer().write(*self.request(),attachments=(a,));self.db._storage.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.assertNotIn(b'sensitive unique attachment contents',(self.root/'store.sqlite').read_bytes())
    def test_prepare_has_no_published_files_or_references(self):
        self.start();self.writer().prepare(*self.request(),attachments=(self.attachment(),));self.assertEqual(self.count('blob_objects'),0);self.assertEqual(list((self.root/'blocks').iterdir()),[])
    def test_duplicate_typed_id_rejected_before_nonce(self):
        self.start();a=self.attachment();self.reject('DUPLICATE_ATTACHMENT',lambda:self.writer().prepare(*self.request(),attachments=(a,a)));self.assertEqual(self.count('issued_nonces'),0)
    def test_duplicate_chunk_position_rejected(self):
        self.start();a=self.attachment();b=self.attachment(plain=b'other');self.reject('DUPLICATE_ATTACHMENT',lambda:self.writer().prepare(*self.request(),attachments=(a,b)))
    def test_out_of_context_rejected_before_nonce(self):
        self.start();self.reject('BLOCK_CONTEXT_MISMATCH',lambda:self.writer().prepare(*self.request(),attachments=(self.attachment(header={2:2}),)));self.assertEqual(self.count('issued_nonces'),0)
    def test_bad_aead_rejected_before_nonce(self):
        self.start();self.reject('AEAD_INVALID',lambda:self.writer().prepare(*self.request(),attachments=(self.attachment(secret=h('wrong')),)));self.assertEqual(self.count('issued_nonces'),0)
    def test_more_than_128_blocks_rejected(self):
        self.start();self.reject('BLOB_LIMIT',lambda:self.writer().prepare(*self.request(),attachments=tuple(self.attachment(i) for i in range(129))))
    def test_aggregate_byte_budget_is_enforced(self):
        self.start();self.reject('BLOB_LIMIT',lambda:self.writer().prepare(*self.request(),attachments=tuple(self.attachment(i,plain=b'x'*262144) for i in range(32))))
    def test_list_instead_of_tuple_rejected(self):
        self.start();self.reject('BLOB_INPUT',lambda:self.writer().prepare(*self.request(),attachments=[self.attachment()]))
    def test_same_op_different_attachment_rejected(self):
        self.start();w=self.writer();w.write(*self.request(),attachments=(self.attachment(),));self.reject('OPERATION_CONFLICT',lambda:w.write(*self.request(),attachments=(self.attachment(plain=b'different'),)))
    def test_same_op_reordered_attachments_rejected(self):
        self.start();w=self.writer();a=(self.attachment(),self.attachment(1));w.write(*self.request(),attachments=a);self.reject('OPERATION_CONFLICT',lambda:w.write(*self.request(),attachments=a[::-1]))
    def test_same_op_empty_attachment_change_rejected(self):
        self.start();w=self.writer();w.write(*self.request(),attachments=(self.attachment(),));self.reject('OPERATION_CONFLICT',lambda:w.write(*self.request()))
    def test_same_op_retry_no_nonce_or_file_republication(self):
        self.start();w=self.writer();a=(self.attachment(),);r=w.write(*self.request(),attachments=a);n=self.count('issued_nonces');events=[];self.db.observer=events.append;self.assertEqual(w.write(*self.request(),attachments=a),r);self.assertEqual(self.count('issued_nonces'),n);self.assertEqual(events,[])
    def test_retry_after_revocation_is_result_recovery(self):
        self.start();w=self.writer();a=(self.attachment(),);r=w.write(*self.request(),attachments=a);self.next_epoch(entries=self.s.entries[1:]);self.assertEqual(w.read_committed(*self.request(),attachments=a),r)
    def test_stale_authority_cannot_publish_references(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));self.same_epoch();self.reject('STALE_DECISION',lambda:self.db.commit(p));self.assertEqual(self.count('blob_references'),0)
    def test_reader_cannot_publish(self):
        self.start();self.reject('NOT_AUTHORIZED',lambda:self.writer(index=1).write(*self.request(index=1),attachments=(self.attachment(),)))
    def test_mutated_candidate_is_rejected(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));self.reject('CANDIDATE_INVALID',lambda:self.db.commit(replace(p,manifest=b'bad')))
    def test_stripping_blob_ticket_is_not_bypass(self):
        self.start();p=self.writer().prepare(*self.request(),attachments=(self.attachment(),));self.reject('ATTACHMENT_BINDING_REQUIRED',lambda:self.db.commit(p.bound))
    def test_distinct_envelopes_share_immutable_block(self):
        self.start();a=(self.attachment(),);w=self.writer();r=w.write(*self.request(),attachments=a);w.write(*self.request(op=2,sequence=2,previous=r.envelope_id),attachments=a);self.assertEqual(self.count('blob_objects'),1);self.assertEqual(self.count('blob_references'),2);self.assertTrue(self.db.audit()['valid'])
    def test_legacy_non_blob_writer_still_works(self):
        self.start();self.legacy_writer().write(*self.request());self.assertEqual(self.count('blob_commit_roots'),1);self.assertTrue(self.db.audit()['valid'])
    def test_new_empty_manifest_not_confused_with_missing(self):
        self.start();self.writer().write(*self.request());self.assertEqual(self.count('blob_commit_roots'),1);self.assertTrue(self.db.audit()['valid']);self.db._storage.connection.execute('DELETE FROM blob_commit_roots');self.assertFalse(self.db.audit()['valid'])
    def test_auth_change_during_preparation_invalidates_result(self):
        self.start()
        def hook(stage):
            if stage=='crypto.before_store_commit':self.same_epoch()
        self.reject('STALE_DECISION',lambda:self.writer(observer=hook).write(*self.request(),attachments=(self.attachment(),)));self.assertEqual(self.count('blob_objects'),0)
    def test_precommit_file_corruption_rolls_back_refs(self):
        self.start();a=self.attachment();loc=hashlib.sha256(a.sealed_bytes).hexdigest()
        def hook(stage):
            if stage=='commit.after_blocks':(self.root/'blocks'/loc).write_bytes(b'bad')
        self.db.observer=hook;self.reject('BLOCK_CORRUPT',lambda:self.writer().write(*self.request(),attachments=(a,)));self.assertEqual(self.count('blob_objects'),0);self.assertEqual(self.count('commit_ledger'),0)
    def test_reentrant_commit_is_rejected(self):
        self.start();w=self.writer();seen=[]
        def hook(stage):
            if stage=='commit.after_begin':
                try:w.write(*self.request(op=2))
                except StoreError as e:seen.append(e.code)
        self.db.observer=hook;w.write(*self.request(),attachments=(self.attachment(),));self.assertEqual(seen,['REENTRANT_OPERATION'])
    def test_block_paths_only_use_raw_digest(self):
        self.start();a=self.attachment();self.writer().write(*self.request(),attachments=(a,));self.assertTrue((self.root/'blocks'/hashlib.sha256(a.sealed_bytes).hexdigest()).exists());self.assertFalse((self.root/'blocks'/a.typed_id.hex()).exists())
    def test_observer_sees_no_refs_before_commit(self):
        self.start();seen=[]
        def hook(stage):
            if stage=='block.after_dirsync':seen.append(self.count('blob_references'))
        self.db.observer=hook;self.writer().write(*self.request(),attachments=(self.attachment(),));self.assertEqual(seen,[0])
    def test_gc_is_dry_run_until_reader_and_closure_pins_exist(self):
        self.start();orphan=b'public orphan test';bid=self.db._storage.block_port.publish(orphan);report=self.db.orphan_report();self.assertIn(bid.hex(),report['unreferenced_locators']);self.assertFalse(report['deletion_performed']);self.assertTrue((self.root/'blocks'/bid.hex()).exists())
