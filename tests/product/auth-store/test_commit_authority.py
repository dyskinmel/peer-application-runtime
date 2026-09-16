from auth_store_support import *
from dataclasses import replace
class CommitAuthorityTests(AuthStoreTest):
    def test_atomic_write_links_authority_and_ledger(self):
        self.start();r=self.writer().write(*self.request());self.assertEqual(self.count('auth_commits'),1);self.assertEqual(self.count('commit_ledger'),1);self.assertTrue(self.db.audit()['valid']);self.assertEqual(r.envelope_id,self.db._storage.connection.execute('SELECT commit_id FROM commit_ledger').fetchone()[0])
    def test_candidate_never_claims_inner_crdt_applied(self):
        self.start();r=self.writer().write(*self.request());self.assertEqual(self.db._storage.connection.execute('SELECT state FROM envelopes').fetchone()[0],'pending');self.assertFalse(self.db.status(self.s.space)['automerge_validated'])
    def test_preparation_issues_nonce_but_no_data(self):
        self.start();c=self.writer().prepare(*self.request());self.assertEqual(self.count('issued_nonces'),3);self.assertEqual(self.count('commit_ledger'),0);self.assertNotIn('opaque inner',repr(c))
    def test_reader_rejected_before_nonce(self):
        self.start();self.reject('NOT_AUTHORIZED',lambda:self.writer(1).prepare(*self.request(index=1)));self.assertEqual(self.count('issued_nonces'),0)
    def test_keeper_rejected(self):
        self.start();self.reject('NOT_AUTHORIZED',lambda:self.writer(2).prepare(*self.request(index=2)))
    def test_membership_pending_rejected(self):
        self.start('control');self.reject('MEMBERSHIP_REQUIRED',lambda:self.writer().prepare(*self.request()))
    def test_seed_pending_rejected(self):
        self.start('membership');self.reject('EPOCH_PENDING',lambda:self.writer().prepare(*self.request()))
    def test_stale_head_same_epoch_rejected(self):
        self.start();c=self.writer().prepare(*self.request());self.same_epoch();self.reject('STALE_DECISION',lambda:self.db.commit(c));self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('issued_nonces'),3)
    def test_revoked_editor_cannot_commit_prepared_write(self):
        self.start();c=self.writer().prepare(*self.request());self.next_epoch(entries=self.s.entries[1:]);self.reject('STALE_DECISION',lambda:self.db.commit(c));self.assertEqual(self.count('commit_ledger'),0)
    def test_fork_cannot_commit_prepared_write(self):
        self.start();c=self.writer().prepare(*self.request());b=dict(self.b['body']);b[9]=h('fork');self.reject('CONTROL_FORK',lambda:self.db.observe(self.s.space,self.s.raw(b)));self.reject('STALE_DECISION',lambda:self.db.commit(c))
    def test_activation_revision_invalidates_older_candidate(self):
        self.start();c=self.writer().prepare(*self.request());self.activate();self.reject('STALE_DECISION',lambda:self.db.commit(c))
    def test_retry_returns_exact_receipt_without_nonce(self):
        self.start();w=self.writer();r=w.write(*self.request());n=self.count('issued_nonces');self.assertEqual(w.write(*self.request()),r);self.assertEqual(self.count('issued_nonces'),n)
    def test_committed_result_remains_queryable_after_revoke(self):
        self.start();w=self.writer();r=w.write(*self.request());self.next_epoch(entries=self.s.entries[1:]);self.assertEqual(w.read_committed(*self.request()),r);self.assertEqual(w.write(*self.request()),r);self.assertEqual(self.count('issued_nonces'),3)
    def test_changed_retry_input_rejected(self):
        self.start();w=self.writer();w.write(*self.request());op,hdr,p,c=self.request();self.reject('OPERATION_CONFLICT',lambda:w.write(op,hdr,p,c+b'x'))
    def test_wrong_epoch_secret_rejected_before_nonce(self):
        self.start();self.reject('EPOCH_SECRET_MISMATCH',lambda:self.writer(secret=h('wrong-key')).prepare(*self.request()));self.assertEqual(self.count('issued_nonces'),0)
    def test_header_author_mismatch_rejected(self):
        self.start();req=self.request();req[1][5]=self.s.devices[1]['id'];self.reject('AUTH_CONTEXT_MISMATCH',lambda:self.writer().prepare(*req))
    def test_header_space_mismatch_rejected(self):
        self.start();req=self.request();req[1][1]=h('wrong-space');self.reject(None,lambda:self.writer().prepare(*req))
    def test_header_control_mismatch_rejected(self):
        self.start();req=self.request();req[1][13]=h('wrong-head');self.reject('AUTH_CONTEXT_MISMATCH',lambda:self.writer().prepare(*req))
    def test_header_epoch_mismatch_rejected(self):
        self.start();req=self.request();req[1][2]=2;self.reject('AUTH_CONTEXT_MISMATCH',lambda:self.writer().prepare(*req))
    def test_raw_store_commit_is_not_public_bypass(self):
        self.start();c=self.writer().prepare(*self.request());self.reject('AUTHORIZATION_REQUIRED',lambda:self.db._storage.commit(c.prepared,fencing_token=self.db._storage.fencing_token))
    def test_candidate_prepared_bytes_are_bound(self):
        self.start();c=self.writer().prepare(*self.request());p=replace(c.prepared,encrypted_cache=b'changed');self.reject('CANDIDATE_INVALID',lambda:self.db.commit(replace(c,prepared=p)))
    def test_candidate_revision_is_bound(self):
        self.start();c=self.writer().prepare(*self.request());self.reject('CANDIDATE_INVALID',lambda:self.db.commit(replace(c,revision=c.revision+1)))
    def test_candidate_device_is_bound(self):
        self.start();c=self.writer().prepare(*self.request());self.reject('CANDIDATE_INVALID',lambda:self.db.commit(replace(c,device_id=self.s.devices[1]['id'])))
    def test_old_candidate_after_reopen_is_rejected(self):
        self.start();c=self.writer().prepare(*self.request());self.reopen();self.activate();self.reject('CANDIDATE_INVALID',lambda:self.db.commit(c))
    def test_reentrant_write_during_commit_is_rejected(self):
        self.start();w=self.writer();c=w.prepare(*self.request());seen=[]
        def hook(stage):
            if stage=='commit.after_begin':
                try:self.db.observe(self.s.space,self.b['raw'])
                except StoreError as e:seen.append(e.code)
        self.db.observer=hook;self.db.commit(c);self.assertEqual(seen,['REENTRANT_OPERATION'])
    def test_revocation_between_crypto_and_commit_is_detected(self):
        self.start()
        def hook(stage):
            if stage=='crypto.before_store_commit':self.next_epoch(entries=self.s.entries[1:])
        self.reject('STALE_DECISION',lambda:self.writer(observer=hook).write(*self.request()));self.assertEqual(self.count('commit_ledger'),0)
    def test_abort_leaves_nonce_issued(self):
        self.start();c=self.writer().prepare(*self.request())
        def hook(stage):
            if stage=='commit.after_ledger':raise RuntimeError('injected')
        self.db.observer=hook;self.reject('LOCAL_ABORTED',lambda:self.db.commit(c));self.assertEqual(self.count('issued_nonces'),3);self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('auth_commits'),0)
    def test_response_loss_is_unknown_and_queryable(self):
        self.start();w=self.writer()
        def hook(stage):
            if stage=='commit.after_commit':raise RuntimeError('response lost')
        self.db.observer=hook;self.reject('LOCAL_OUTCOME_UNKNOWN',lambda:w.write(*self.request()));self.db.observer=None;self.assertIsNotNone(w.read_committed(*self.request()));self.assertEqual(self.count('auth_commits'),1)
    def test_second_sequence_links_previous_envelope(self):
        self.start();w=self.writer();first=w.write(*self.request());r=w.write(*self.request(op=2,sequence=2,previous=first.envelope_id));self.assertNotEqual(r,first);self.assertEqual(self.count('auth_commits'),2);self.assertTrue(self.db.audit()['valid'])
    def test_actor_gap_rejects_entire_authorized_commit(self):
        self.start();self.reject('ACTOR_CONFLICT',lambda:self.writer().write(*self.request(sequence=2)));self.assertEqual(self.count('auth_commits'),0)
    def test_new_epoch_allows_fresh_authorized_writer(self):
        self.start();self.writer().write(*self.request());b=self.next_epoch();self.activate(b);w=self.writer(secret=b['secret']);r=w.write(*self.request(op=2,b=b));self.assertIsNotNone(r);self.assertEqual(self.count('auth_epoch_keys'),2);self.assertTrue(self.db.audit()['valid'])
    def test_rotation_then_same_epoch_write_uses_current_head(self):
        self.start();body=self.s.next(self.b['raw'],4);raw=self.s.raw(body,new_seed=self.s.owner1);self.db.observe(self.s.space,raw);self.db.provide_membership(self.s.space,self.b['pages']);req=self.request();req[1][13]=control_id(raw);self.assertIsNotNone(self.writer().write(*req));self.assertTrue(self.db.audit()['valid'])
    def test_known_operation_with_bad_proof_is_not_returned(self):
        self.start();w=self.writer();w.write(*self.request());self.db._storage.connection.execute('UPDATE auth_commits SET proof_digest=?',(h('bad'),));self.reject('AUTH_STORE_CORRUPT',lambda:w.read_committed(*self.request()))
    def test_unrelated_space_cannot_accept_bound_candidate(self):
        self.start();c=self.writer().prepare(*self.request());other=Path(self.tmp.name)/'other';db=self.m.AuthorityStore.create(other,provider=self.p,allow_unpatched_sqlite=True);self.addCleanup(db.close);self.reject('CANDIDATE_INVALID',lambda:db.commit(c))
    def test_supplied_header_is_owned_before_observer_mutates_it(self):
        self.start();req=self.request();original=req[1][13]
        def alter(stage):req[1][13]=h('mutated')
        r=self.writer(observer=alter).write(*req);stored=self.db._storage.connection.execute('SELECT encrypted_bytes FROM envelopes').fetchone()[0];self.assertEqual(decode(decode(stored)[0])[13],original)
    def test_stale_fence_rejects_old_candidate(self):
        self.start();candidate=self.writer().prepare(*self.request());self.db._storage.rotate_fence();self.reject('CANDIDATE_INVALID',lambda:self.db.commit(candidate))
    def test_wrong_thread_is_rejected(self):
        import threading
        self.start();codes=[]
        def call():
            try:self.db.status(self.s.space)
            except StoreError as e:codes.append(e.code)
        t=threading.Thread(target=call);t.start();t.join(5);self.assertFalse(t.is_alive());self.assertEqual(codes,['WRONG_THREAD'])
