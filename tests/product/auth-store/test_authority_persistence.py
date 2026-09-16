from auth_store_support import *
class PersistenceTests(AuthStoreTest):
    def test_enrollment_requires_external_space_anchor(self):
        self.db=self.m.AuthorityStore.create(self.root,provider=self.p,allow_unpatched_sqlite=True)
        self.reject('TRUST_ANCHOR',lambda:self.db.enroll(self.s.app,h('wrong'),self.s.genesis));self.assertEqual(self.count('auth_spaces'),0)
    def test_enrollment_is_idempotent_without_revision_change(self):
        self.start();before=self.db.pin(self.s.space);self.db.enroll(self.s.app,self.s.space,self.s.genesis);self.assertEqual(self.db.pin(self.s.space),before)
    def test_duplicate_control_does_not_advance_revision(self):
        self.start();before=self.db.pin(self.s.space);self.assertEqual(self.db.observe(self.s.space,self.b['raw']),'DUPLICATE');self.assertEqual(before,self.db.pin(self.s.space))
    def test_invalid_signature_is_not_persisted_as_fork(self):
        self.start();raw=decode(self.b['raw']);raw[1]=b'0'*64;before=self.db.pin(self.s.space)
        self.reject('CRYPTO_INVALID',lambda:self.db.observe(self.s.space,encode(raw)));self.assertEqual(before,self.db.pin(self.s.space))
    def test_pending_control_survives_restart(self):
        self.start('control');self.reopen();self.assertEqual(self.db.status(self.s.space)['state'],'MEMBERSHIP_PENDING')
    def test_restart_requires_key_revalidation(self):
        self.start();pin=self.db.pin(self.s.space);self.reopen(expected_pins=[pin]);self.assertEqual(self.db.status(self.s.space)['state'],'EPOCH_PENDING');self.reject('EPOCH_PENDING',lambda:self.writer().prepare(*self.request()));self.activate();self.assertIsNotNone(self.writer().write(*self.request()))
    def test_signed_fork_is_durable(self):
        self.start();b=dict(self.b['body']);b[9]=h('alternate-root');self.reject('CONTROL_FORK',lambda:self.db.observe(self.s.space,self.s.raw(b)));self.reopen();self.assertEqual(self.db.status(self.s.space)['state'],'CONTROL_FORK');self.reject('CONTROL_FORK',lambda:self.activate())
    def test_invalid_content_policy_is_durable(self):
        self.start();entries=[dict(x) for x in self.s.entries];entries[0][2]=1;pages=pages_for(entries);b=self.s.next(self.b['raw']);b[6]=member_root(pages);self.db.observe(self.s.space,self.s.raw(b));self.reject('CONTENT_MEMBERSHIP_CHANGED',lambda:self.db.provide_membership(self.s.space,pages));self.reopen();self.assertEqual(self.db.status(self.s.space)['state'],'CONTROL_INVALID')
    def test_key_fingerprint_survives_reopen(self):
        self.start();finger=self.db._storage.connection.execute('SELECT key_check FROM auth_epoch_keys').fetchone()[0];self.reopen();self.assertEqual(self.db._storage.connection.execute('SELECT key_check FROM auth_epoch_keys').fetchone()[0],finger)
    def test_prior_epoch_secret_reuse_after_restart_rejected(self):
        self.start();b=self.next_epoch(secret=self.s.secret);self.reopen();self.reject('EPOCH_SECRET_REUSED',lambda:self.activate(b));self.assertEqual(self.db.status(self.s.space)['state'],'EPOCH_PENDING')
    def test_same_epoch_conflicting_secret_is_rejected_after_restart(self):
        self.start();self.reopen();self.db._storage.connection.execute('UPDATE auth_epoch_keys SET key_check=?',(h('corrupt'),));self.reject('AUTH_STORE_CORRUPT',lambda:self.activate())
    def test_secret_and_plain_seed_not_in_database(self):
        self.start();c=self.db._storage.connection
        rows=b''.join(bytes(v) if isinstance(v,bytes) else str(v).encode() for table in ['auth_spaces','auth_materials','auth_epoch_keys'] for row in c.execute('SELECT * FROM '+table) for v in row if v is not None)
        for secret in [self.s.secret,self.s.owner,self.s.devices[0]['seed'],self.s.devices[0]['secret'],self.b['plain']]:self.assertNotIn(secret,rows)
    def test_epoch_change_marks_outbox_rebase(self):
        self.start();self.writer().write(*self.request());self.next_epoch();self.assertEqual(self.db._storage.connection.execute('SELECT state FROM outbox').fetchone()[0],'rebase-required');self.assertEqual(self.count('actor_states'),0);self.assertTrue(self.db.audit()['valid'])
    def test_pending_control_hides_outbox(self):
        self.start();self.writer().write(*self.request());self.assertEqual(len(self.db.pending()),1);self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw'])));self.assertEqual(self.db.pending(),[])
    def test_activation_after_reopen_from_saved_encrypted_material(self):
        self.start();self.reopen();d=self.s.devices[0];self.db.reactivate(self.s.space,d['secret']);self.assertEqual(self.db.status(self.s.space)['state'],'ACTIVE')
    def test_future_pin_is_rejected(self):
        self.start();pin=self.db.pin(self.s.space);pin['revision']+=100;self.close();self.reject('AUTH_PIN_STALE',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True,expected_pins=[pin]))
    def test_wrong_genesis_pin_is_rejected(self):
        self.start();pin=self.db.pin(self.s.space);pin['space_id']=h('other').hex();self.close();self.reject('AUTH_PIN_STALE',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True,expected_pins=[pin]))
    def test_direct_head_corruption_blocks_reopen(self):
        self.start();self.db._storage.connection.execute('UPDATE auth_spaces SET head=?',(h('wrong'),));self.close();self.reject('AUTH_STORE_CORRUPT',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_deleted_commit_proof_is_not_ignored(self):
        self.start();self.writer().write(*self.request());self.db._storage.connection.execute('DELETE FROM auth_commits');self.assertFalse(self.db.audit()['valid']);self.close();self.reject('AUTH_STORE_CORRUPT',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_low_level_space_configuration_is_disabled(self):
        self.start();self.reject('AUTHORIZATION_REQUIRED',lambda:self.db._storage.configure_space(h('new'),self.s.app,1,h('head')))
    def test_low_level_epoch_advance_is_disabled(self):
        self.start();self.reject('AUTHORIZATION_REQUIRED',lambda:self.db._storage.advance_epoch(self.s.space,1,2,h('head')))
    def test_failed_valid_revoke_latches_writes_until_retried(self):
        self.start();raw=self.s.raw(self.s.next(self.b['raw']));c=self.writer().prepare(*self.request())
        def fail(stage):
            if stage=='auth.after_row':raise RuntimeError('disk fault surrogate')
        self.db.observer=fail;self.reject('AUTH_UPDATE_ABORTED',lambda:self.db.observe(self.s.space,raw));self.db.observer=None
        self.reject('AUTH_PERSISTENCE_UNCERTAIN',lambda:self.writer().prepare(*self.request(op=2)))
        self.reject('STALE_DECISION',lambda:self.db.commit(c))
        self.db.observe(self.s.space,raw);self.db.provide_membership(self.s.space,self.b['pages']);self.activate();self.assertEqual(self.db.status(self.s.space)['state'],'ACTIVE')
    def test_duplicate_old_control_does_not_clear_persistence_failure(self):
        self.start()
        def fail(stage):
            if stage=='auth.after_row':raise RuntimeError('fault')
        self.db.observer=fail;raw=self.s.raw(self.s.next(self.b['raw']));self.reject('AUTH_UPDATE_ABORTED',lambda:self.db.observe(self.s.space,raw));self.db.observer=None;self.db.observe(self.s.space,self.b['raw'])
        self.reject('AUTH_PERSISTENCE_UNCERTAIN',lambda:self.writer().prepare(*self.request()))
    def test_lost_update_reply_can_be_reconciled_by_exact_retry(self):
        self.start();raw=self.s.raw(self.s.next(self.b['raw']))
        def fail(stage):
            if stage=='auth.after_commit':raise RuntimeError('lost')
        self.db.observer=fail;self.reject('AUTH_OUTCOME_UNKNOWN',lambda:self.db.observe(self.s.space,raw));self.db.observer=None
        self.db.observe(self.s.space,raw);self.db.provide_membership(self.s.space,self.b['pages']);self.activate();self.assertEqual(self.db.status(self.s.space)['state'],'ACTIVE')
    def test_material_corruption_rejected_on_reopen(self):
        self.start();c=self.db._storage.connection;c.execute('UPDATE auth_materials SET encrypted_material=?',(encode({0:b'wrong'}),));self.close();self.reject('AUTH_STORE_CORRUPT',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_history_deletion_does_not_reactivate_old_permissions(self):
        self.start();self.next_epoch(entries=self.s.entries[1:]);c=self.db._storage.connection;c.execute('UPDATE auth_spaces SET replay=?',(b'\xa0',));self.close();self.reject('AUTH_STORE_CORRUPT',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
    def test_wrong_recipient_cannot_reactivate_saved_material(self):
        self.start();self.reopen();self.reject('CRYPTO_INVALID',lambda:self.db.reactivate(self.s.space,h('wrong-recipient-secret')))
    def test_persistence_latch_cannot_clear_with_old_epoch_activation(self):
        self.start()
        def fail(stage):
            if stage=='auth.after_row':raise RuntimeError('fault')
        self.db.observer=fail;self.reject('AUTH_UPDATE_ABORTED',lambda:self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw']))));self.db.observer=None
        self.reject('AUTH_PERSISTENCE_UNCERTAIN',lambda:self.activate())
    def test_restart_keeps_prior_same_epoch_metadata_change(self):
        self.start();raw=self.same_epoch();self.reopen();self.db.reactivate(self.s.space,self.s.devices[0]['secret']);self.assertEqual(self.db.status(self.s.space)['known_head'],control_id(raw).hex())
