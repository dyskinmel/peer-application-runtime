from store_helpers import *

class CoreTests(StoreCase):
    def test_reads_actual_wal_full_foreign_keys(self):
        d=self.s.diagnostics()
        self.assertEqual((d['journal_mode'],d['synchronous'],d['foreign_keys']),('wal',2,1))
        self.assertFalse(d['production_qualified']);self.assertEqual(d['sqlite_version'],sqlite3.sqlite_version)
    def test_complete_atomic_commit(self):
        p=self.prepare();r=self.commit(p)
        self.assertEqual(r.envelope_id,p.envelope_id)
        for table in ('envelopes','commit_ledger','actor_states','catalog','outbox','local_commit_meta'):
            self.assertEqual(self.scalar('SELECT count(*) FROM '+table),1,table)
        self.assertEqual(self.scalar('SELECT state FROM outbox'),'pending')
        self.assertTrue(self.s.audit()['valid'])
    def test_exact_retry_returns_original_receipt(self):
        p=self.prepare();a=self.commit(p);b=self.commit(p)
        self.assertEqual(a,b);self.assertEqual(a.encrypted_receipt,p.encrypted_receipt)
        self.assertEqual(len(self.s.pending()),1)
    def test_reopen_then_retry(self):
        p=self.prepare();a=self.commit(p);self.reopen();self.assertEqual(a,self.commit(p))
    def test_lookup_resolves_lost_response(self):
        p=self.prepare();self.commit(p)
        r=self.s.lookup_operation(p.operation_id,p.input_digest)
        self.assertEqual(r.envelope_id,p.envelope_id)
    def test_lookup_absent_does_not_invent_success(self):
        self.assertIsNone(self.s.lookup_operation(b'z'*16,h('absent')))
    def test_operation_digest_replacement_is_rejected(self):
        p=self.prepare();self.commit(p)
        self.err('OPERATION_CONFLICT',self.commit,replace(p,input_digest=h('other')))
    def test_ciphertext_replacement_under_same_operation_rejected(self):
        p=self.prepare();self.commit(p)
        self.err('OPERATION_CONFLICT',self.commit,replace(p,envelope=b'other-ciphertext'))
    def test_changed_cached_result_under_same_operation_rejected(self):
        p=self.prepare();self.commit(p)
        self.err('OPERATION_CONFLICT',self.commit,replace(p,encrypted_receipt=b'other'))
    def test_lookup_digest_replacement_rejected(self):
        p=self.prepare();self.commit(p)
        self.err('OPERATION_CONFLICT',self.s.lookup_operation,p.operation_id,h('other'))
    def test_reservation_reuse_rejected_even_for_same_operation(self):
        self.prepare()
        self.err('NONCE_REUSED',self.s.reserve_nonce,(1).to_bytes(16,'big'),h('input-1'),KEY,(1).to_bytes(24,'big'))
    def test_nonce_reservation_survives_reopen(self):
        self.prepare();self.reopen()
        self.err('NONCE_REUSED',self.s.reserve_nonce,b'x'*16,h('x'),KEY,(1).to_bytes(24,'big'))
    def test_same_nonce_different_key_is_allowed(self):
        self.prepare();self.s.reserve_nonce(b'x'*16,h('x'),h('different-key'),(1).to_bytes(24,'big'))
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),2)
    def test_failed_commit_does_not_forget_nonce(self):
        p=self.prepare(epoch=2);self.err('EPOCH_MISMATCH',self.commit,p)
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
    def test_operation_intent_digest_immutable_after_failure(self):
        p=self.prepare(epoch=2);self.err('EPOCH_MISMATCH',self.commit,p)
        self.err('OPERATION_CONFLICT',self.s.reserve_nonce,p.operation_id,h('changed'),KEY,b'n'*24)
    def test_fresh_nonce_for_same_uncommitted_intent(self):
        p=self.prepare(epoch=2);self.err('EPOCH_MISMATCH',self.commit,p)
        new=self.s.reserve_nonce(p.operation_id,p.input_digest,KEY,b'n'*24)
        self.commit(replace(p,reservation_id=new,epoch=1))
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),2)
    def test_unknown_reservation_rejected(self):
        p=self.prepare();self.err('RESERVATION_MISMATCH',self.commit,replace(p,reservation_id=b'z'*16))
    def test_other_operations_reservation_rejected(self):
        p=self.prepare();q=self.prepare(2)
        self.err('RESERVATION_MISMATCH',self.commit,replace(p,reservation_id=q.reservation_id))
    def test_stale_writer_fence(self):
        p=self.prepare();old=self.s.fencing_token;self.s.rotate_fence()
        self.err('FENCE_STALE',self.s.commit,p,fencing_token=old)
        self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
    def test_other_store_writer_refused(self):
        self.err('WRITER_BUSY',self.api.Store.open,self.root,allow_unpatched_sqlite=True)
    def test_unknown_space_is_rejected(self):
        p=self.prepare(space_id=h('other'));self.err('SPACE_NOT_READY',self.commit,p)
    def test_epoch_cas(self):
        p=self.prepare();self.s.advance_epoch(SPACE,1,2,h('c2'))
        self.err('EPOCH_MISMATCH',self.commit,p)
    def test_epoch_transition_cas_rejects_stale_expected(self):
        self.err('EPOCH_MISMATCH',self.s.advance_epoch,SPACE,2,3,h('c3'))
    def test_epoch_transition_marks_old_outbox_rebase(self):
        p=self.prepare();self.commit(p);self.s.advance_epoch(SPACE,1,2,h('c2'))
        self.assertEqual(self.scalar('SELECT state FROM outbox'),'rebase-required')
        self.assertEqual(self.s.pending(),[])
    def test_sequence_and_previous_envelope(self):
        p=self.prepare();self.commit(p);q=self.prepare(2,sequence=2,previous=p.envelope_id);self.commit(q)
        self.assertEqual(self.scalar('SELECT last_sequence FROM actor_states'),(2).to_bytes(8,'big'))
    def test_duplicate_actor_sequence_rejected(self):
        self.commit(self.prepare());self.err('ACTOR_CONFLICT',self.commit,self.prepare(2))
    def test_gap_in_actor_sequence_rejected(self):
        self.err('ACTOR_CONFLICT',self.commit,self.prepare(sequence=2))
    def test_previous_envelope_mismatch_rejected(self):
        self.commit(self.prepare());self.err('ACTOR_CONFLICT',self.commit,self.prepare(2,sequence=2,previous=h('wrong')))
    def test_actor_generation_mismatch_rejected(self):
        p=self.prepare();self.commit(p)
        self.err('ACTOR_CONFLICT',self.commit,self.prepare(2,sequence=2,previous=p.envelope_id,actor_generation=b'b'*16))
    def test_u64_encoding_keeps_high_bit(self):
        self.assertEqual(self.model.u64(2**63),b'\x80'+b'\0'*7)
        self.assertEqual(self.model.from_u64(self.model.u64(2**64-1)),2**64-1)
        self.assertLess(self.model.u64(2**63-1),self.model.u64(2**63))
    def test_sequence_overflow_is_not_wrapped(self):
        p=self.prepare();self.commit(p)
        self.s.connection.execute('UPDATE actor_states SET last_sequence=?',((2**64-1).to_bytes(8,'big'),))
        q=self.prepare(2,sequence=2,previous=p.envelope_id)
        self.err('ACTOR_CONFLICT',self.commit,q)
    def test_pending_bytes_are_exact(self):
        p=self.prepare();self.commit(p);rows=self.s.pending()
        self.assertEqual(rows[0]['envelope'],p.envelope)
        self.assertEqual(rows[0]['operation_id'],p.operation_id)
    def test_inflight_requeued_after_restart(self):
        p=self.prepare();self.commit(p);self.s.mark_inflight(p.envelope_id)
        self.reopen();self.assertEqual(self.scalar('SELECT state FROM outbox'),'in-flight')
        self.assertEqual(self.s.recover_outbox(),1);self.assertEqual(len(self.s.pending()),1)
    def test_terminal_and_rebase_states_not_requeued(self):
        p=self.prepare();self.commit(p)
        self.s.connection.execute("UPDATE outbox SET state='retained'")
        self.assertEqual(self.s.recover_outbox(),0);self.assertEqual(self.s.pending(),[])
    def test_sync_downgrade_stops_commit(self):
        p=self.prepare();self.s.connection.execute('PRAGMA synchronous=NORMAL')
        self.err('SETTINGS_MISMATCH',self.commit,p)
    def test_foreign_keys_downgrade_stops_commit(self):
        p=self.prepare();self.s.connection.execute('PRAGMA foreign_keys=OFF')
        self.err('SETTINGS_MISMATCH',self.commit,p)
    def test_not_database_is_preserved(self):
        other=Path(self.tmp.name)/'bad';other.mkdir();bad=other/'store.sqlite';data=b'not a database';bad.write_bytes(data)
        self.err('CORRUPT_STORE',self.api.Store.open,other,allow_unpatched_sqlite=True)
        self.assertEqual(bad.read_bytes(),data)
    def test_open_missing_does_not_create_database(self):
        root=Path(self.tmp.name)/'missing'
        self.err('STORE_MISSING',self.api.Store.open,root,allow_unpatched_sqlite=True)
        self.assertFalse(root.exists())
    def test_create_refuses_existing_database(self):
        self.err('STORE_EXISTS',self.api.Store.create,self.root,allow_unpatched_sqlite=True)
    def test_schema_version_rejected(self):
        self.s.connection.execute('PRAGMA user_version=999');self.s.close()
        self.err('SCHEMA_MISMATCH',self.api.Store.open,self.root,allow_unpatched_sqlite=True)
    def test_closed_store_not_used(self):
        p=self.prepare();self.s.close();self.err('STORE_CLOSED',self.commit,p)
    def test_audit_detects_deleted_outbox(self):
        self.commit(self.prepare());self.s.connection.execute('DELETE FROM outbox')
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_envelope_bytes_corruption(self):
        self.commit(self.prepare());self.s.connection.execute("UPDATE envelopes SET encrypted_bytes=x'00'")
        self.assertFalse(self.s.audit()['valid'])
    def test_dependency_edges_atomic(self):
        p=self.prepare(dependencies=(h('d1'),h('d2')));self.commit(p)
        self.assertEqual({x[0] for x in self.query('SELECT required_change_hash FROM dependency_edges')},set(p.dependencies))
    def test_no_claim_of_crypto_validation(self):
        d=self.s.diagnostics();self.assertFalse(d['cryptography_verified']);self.assertEqual(d['payload_contract'],'PRESEALED_OPAQUE_BYTES')
    def test_sqlite_patch_classifier(self):
        for v in ('3.51.3','3.52.0','3.50.7','3.44.6'):
            self.assertTrue(self.model.wal_reset_fixed(v),v)
        for v in ('3.46.1','3.51.2','3.50.6','3.44.5'):
            self.assertFalse(self.model.wal_reset_fixed(v),v)
    def test_unpatched_sqlite_requires_explicit_experiment_consent(self):
        if not self.model.wal_reset_fixed(sqlite3.sqlite_version):
            self.err('SQLITE_PATCH_REQUIRED',self.api.Store.create,Path(self.tmp.name)/'production-like')
        else:
            self.assertTrue(self.s.diagnostics()['wal_reset_fix_known'])

# Each malformed input is a separate stable test identity, not a passing loop count.
BAD_FIELDS={
 'op_len':('operation_id',b'x'), 'input_len':('input_digest',b'x'),
 'space_len':('space_id',b'x'), 'object_len':('object_id',b'x'),
 'actor_len':('actor_id',b'x'), 'generation_len':('actor_generation',b'x'),
 'change_len':('change_hash',b'x'), 'reservation_len':('reservation_id',b'x'),
 'epoch_bool':('epoch',True), 'epoch_negative':('epoch',-1),'epoch_overflow':('epoch',2**64),
 'seq_zero':('sequence',0),'seq_bool':('sequence',True),'seq_overflow':('sequence',2**64),
 'prev_len':('previous_envelope',b'x'), 'envelope_type':('envelope','plaintext'),
 'envelope_empty':('envelope',b''),'envelope_large':('envelope',b'x'*1048576),
 'cache_type':('encrypted_cache','plain'), 'receipt_empty':('encrypted_receipt',b''),
 'deps_duplicate':('dependencies',(h('x'),h('x'))),'deps_invalid':('dependencies',(b'x',)),
 'blocks_list':('blocks',[]),'blocks_empty_value':('blocks',(b'',)),
}
def malformed_test(field,value):
    def check(self):
        p=self.prepare();self.err('INVALID_INPUT',self.commit,replace(p,**{field:value}))
        self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
    return check
for name,(field,value) in BAD_FIELDS.items():setattr(CoreTests,'test_reject_'+name,malformed_test(field,value))

class ReviewIntegrityTests(StoreCase):
    def test_audit_detects_missing_actor(self):
        self.commit(self.prepare());self.s.connection.execute('DELETE FROM actor_states')
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_missing_catalog(self):
        self.commit(self.prepare());self.s.connection.execute('DELETE FROM catalog')
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_actor_stale_but_existing_envelope(self):
        p=self.prepare();self.commit(p);self.commit(self.prepare(2,sequence=2,previous=p.envelope_id))
        self.s.connection.execute('UPDATE actor_states SET last_sequence=?,previous_envelope=?',((1).to_bytes(8,'big'),p.envelope_id))
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_stale_catalog_cache(self):
        p=self.prepare();self.commit(p);self.commit(self.prepare(2,sequence=2,previous=p.envelope_id))
        self.s.connection.execute('UPDATE catalog SET encrypted_snapshot_ref=?',(p.encrypted_cache,))
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_changed_nonce_input_digest(self):
        self.commit(self.prepare());self.s.connection.execute('UPDATE issued_nonces SET payload_digest=?',(h('other'),))
        self.assertFalse(self.s.audit()['valid'])
    def test_audit_detects_schema_drift(self):
        self.s.connection.execute('CREATE TABLE unexpected(x TEXT)')
        self.assertFalse(self.s.audit()['valid'])
    def test_open_rejects_schema_drift_before_writes(self):
        self.s.connection.execute('CREATE TABLE unexpected(x TEXT)');self.s.close()
        self.err('SCHEMA_MISMATCH',self.api.Store.open,self.root,allow_unpatched_sqlite=True)
    def test_new_epoch_zero_actor_states_is_valid(self):
        self.commit(self.prepare());self.s.advance_epoch(SPACE,1,2,h('c2'))
        self.assertTrue(self.s.audit()['valid'])
    def test_pending_reentrant_read_is_refused(self):
        p=self.prepare();seen=[]
        def observer(stage):
            if stage=='commit.after_outbox':
                try:self.s.pending()
                except Exception as exc:seen.append(getattr(exc,'code',None))
        self.s.observer=observer;self.commit(p);self.s.observer=None
        self.assertEqual(seen,['REENTRANT_OPERATION'])
    def test_lookup_reentrant_read_is_refused(self):
        p=self.prepare();seen=[]
        def observer(stage):
            if stage=='commit.after_meta':
                try:self.s.lookup_operation(p.operation_id,p.input_digest)
                except Exception as exc:seen.append(getattr(exc,'code',None))
        self.s.observer=observer;self.commit(p);self.s.observer=None
        self.assertEqual(seen,['REENTRANT_OPERATION'])
    def test_pending_limit_and_cursor(self):
        p=self.prepare();self.commit(p);q=self.prepare(2,sequence=2,previous=p.envelope_id);self.commit(q)
        first=self.s.pending(limit=1);second=self.s.pending(limit=1,after=first[0]['envelope_id'])
        self.assertEqual(len(first),1);self.assertEqual(len(second),1)
        self.assertEqual({first[0]['envelope_id'],second[0]['envelope_id']},{p.envelope_id,q.envelope_id})
    def test_pending_limit_invalid(self):
        for limit in (0,1025,True,-1):self.err('INVALID_INPUT',self.s.pending,limit=limit)
    def test_u64_sequence_crosses_signed_boundary_in_store(self):
        p=self.prepare();self.commit(p)
        self.s.connection.execute('UPDATE actor_states SET last_sequence=?',((2**63-1).to_bytes(8,'big'),))
        q=self.prepare(2,sequence=2**63,previous=p.envelope_id);self.commit(q)
        self.assertEqual(self.scalar('SELECT last_sequence FROM actor_states'),(2**63).to_bytes(8,'big'))
    def test_different_store_cannot_use_reservation_id(self):
        p=self.prepare();other=Path(self.tmp.name)/'other'
        with self.api.Store.create(other,allow_unpatched_sqlite=True) as s:
            s.configure_space(SPACE,'org.example.notes',1,CONTROL)
            self.err('RESERVATION_MISMATCH',s.commit,p,fencing_token=s.fencing_token)
