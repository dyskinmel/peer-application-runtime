from blob_support import *
class IncomingTests(BlobTest):
    def setUp(self):
        super().setUp();self.assertTrue(hasattr(self.blob,'IncomingQueue'),'bounded durable incoming queue not implemented');self.q=None;self.addCleanup(self.close_queue);self.qroot=Path(self.tmp.name)/'incoming'
    def close_queue(self):
        if self.q:self.q.close();self.q=None
    def begin(self,a=None,**limits):
        a=a or self.attachment();self.q=self.blob.IncomingQueue.create(self.qroot,**limits);t=self.q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes));return a,t
    def reopen_queue(self):
        self.close_queue();self.q=self.blob.IncomingQueue.open(self.qroot)
    def finish(self,t):return self.q.finish(t,self.p,self.s.secret,app=self.s.app,space=self.s.space,epoch=1)
    def test_chunked_receive_finishes_exact_attachment(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.q.append(t,10,a.sealed_bytes[10:]);self.assertEqual(self.finish(t),a)
    def test_durable_offset_resume(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.reopen_queue();self.assertEqual(self.q.status(t)['acknowledged_bytes'],10);self.q.append(t,10,a.sealed_bytes[10:]);self.assertEqual(self.finish(t),a)
    def test_duplicate_received_range_is_idempotent(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:20]);self.assertEqual(self.q.append(t,0,a.sealed_bytes[:10]),20)
    def test_different_retry_prefix_rejected(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:20]);self.reject('TRANSFER_CONFLICT',lambda:self.q.append(t,0,b'x'*10))
    def test_gap_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_OFFSET',lambda:self.q.append(t,1,a.sealed_bytes[:10]))
    def test_overlap_extending_tail_rejected(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.reject('TRANSFER_OFFSET',lambda:self.q.append(t,5,a.sealed_bytes[5:20]))
    def test_oversized_transfer_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_LIMIT',lambda:self.q.begin(a.typed_id,a.header_bytes,1000000))
    def test_item_budget_enforced(self):
        a,t=self.begin(max_items=1);self.reject('TRANSFER_LIMIT',lambda:self.q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes)))
    def test_reserved_total_budget_enforced(self):
        a=self.attachment();a,t=self.begin(a,max_bytes=len(a.sealed_bytes));self.reject('TRANSFER_LIMIT',lambda:self.q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes)))
    def test_append_past_expected_size_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_LIMIT',lambda:self.q.append(t,0,a.sealed_bytes+b'x'))
    def test_incomplete_finish_rejected(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.reject('TRANSFER_INCOMPLETE',lambda:self.finish(t))
    def test_wrong_digest_never_promotes(self):
        a,t=self.begin();self.q.append(t,0,b'x'*len(a.sealed_bytes));self.reject('BLOCK_ID_MISMATCH',lambda:self.finish(t));self.assertFalse(self.q.status(t)['referenced'])
    def test_correct_hash_but_wrong_aead_rejected(self):
        a,t=self.begin(self.attachment(secret=h('bad-secret')));self.q.append(t,0,a.sealed_bytes);self.reject('AEAD_INVALID',lambda:self.finish(t))
    def test_wrong_expected_space_rejected(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes);self.reject('BLOCK_CONTEXT_MISMATCH',lambda:self.q.finish(t,self.p,self.s.secret,app=self.s.app,space=h('other'),epoch=1))
    def test_unknown_token_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_MISSING',lambda:self.q.status('0'*32))
    def test_path_traversal_token_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_INPUT',lambda:self.q.status('../store'))
    def test_shorter_acknowledged_file_rejected_on_open(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.close_queue();(self.qroot/(t+'.part')).write_bytes(b'bad');self.reject('TRANSFER_CORRUPT',self.reopen_queue)
    def test_changed_acknowledged_prefix_rejected_on_open(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.close_queue();(self.qroot/(t+'.part')).write_bytes(b'x'*10);self.reject('TRANSFER_CORRUPT',self.reopen_queue)
    def test_unacknowledged_tail_discarded(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes[:10]);self.close_queue()
        with (self.qroot/(t+'.part')).open('ab') as f:f.write(b'not acknowledged')
        self.reopen_queue();self.assertEqual((self.qroot/(t+'.part')).stat().st_size,10);self.q.append(t,10,a.sealed_bytes[10:]);self.assertEqual(self.finish(t),a)
    def test_full_validation_does_not_create_store_receipt(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes);self.finish(t);self.assertFalse(self.q.status(t)['referenced']);self.assertFalse((self.qroot/'store.sqlite').exists())
    def test_queue_has_exclusive_writer_lock(self):
        a,t=self.begin();self.reject('WRITER_BUSY',lambda:self.blob.IncomingQueue.open(self.qroot))
    def test_symlinked_part_is_rejected(self):
        a,t=self.begin();self.close_queue();(self.qroot/(t+'.part')).unlink();out=Path(self.tmp.name)/'elsewhere';out.write_bytes(b'');(self.qroot/(t+'.part')).symlink_to(out);self.reject(None,self.reopen_queue)
    def test_complete_transfer_can_be_committed_by_authorized_writer(self):
        a,t=self.begin();self.q.append(t,0,a.sealed_bytes);received=self.finish(t);self.start();r=self.writer().write(*self.request(),attachments=(received,));self.assertEqual(self.db.read_attachment(r.envelope_id,0,self.s.secret),b'synthetic attachment')
    def test_closed_queue_rejected(self):
        a,t=self.begin();q=self.q;self.close_queue();self.reject('TRANSFER_CLOSED',lambda:q.status(t))
    def test_append_boolean_offset_rejected(self):
        a,t=self.begin();self.reject('TRANSFER_INPUT',lambda:self.q.append(t,False,b'a'))
    def test_explicit_discard_releases_spool_capacity(self):
        a,t=self.begin(max_items=1);self.assertTrue(hasattr(self.q,'discard'),'explicit spool cleanup not implemented');self.q.append(t,0,a.sealed_bytes);self.q.discard(t);self.reject('TRANSFER_MISSING',lambda:self.q.status(t));self.assertIsNotNone(self.q.begin(a.typed_id,a.header_bytes,len(a.sealed_bytes)))
    def test_discard_does_not_delete_committed_store_file(self):
        a,t=self.begin();self.assertTrue(hasattr(self.q,'discard'),'explicit spool cleanup not implemented');self.q.append(t,0,a.sealed_bytes);received=self.finish(t);self.start();r=self.writer().write(*self.request(),attachments=(received,));self.q.discard(t);self.assertEqual(self.db.read_attachment(r.envelope_id,0,self.s.secret),b'synthetic attachment')
    def test_metadata_ack_response_loss_requires_reopen(self):
        a,t=self.begin()
        def hook(stage):
            if stage=='incoming.after_ack_publish':raise RuntimeError('lost response')
        self.q.observer=hook;self.reject('TRANSFER_OUTCOME_UNKNOWN',lambda:self.q.append(t,0,a.sealed_bytes));self.reject('TRANSFER_RECOVERY_REQUIRED',lambda:self.q.status(t));self.reopen_queue();self.assertEqual(self.finish(t),a)
    def test_reentrant_append_does_not_change_offset(self):
        a,t=self.begin();seen=[]
        def hook(stage):
            if stage=='incoming.after_data_write':
                try:self.q.append(t,0,b'x')
                except StoreError as e:seen.append(e.code)
        self.q.observer=hook;self.q.append(t,0,a.sealed_bytes);self.assertEqual(seen,['REENTRANT_OPERATION']);self.assertEqual(self.finish(t),a)
