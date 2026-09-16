from apply_support import ApplyTest,h

class StorageTests(ApplyTest):
    def test_exact_atomic_set_and_encrypted_note(self):
        e,cid=self.saved();r=self.call([e]);self.assertEqual(self.nums(),{'document_inputs':1,'document_apply_events':1,'document_frontiers':1,'document_apply_nonces':1})
        self.assertEqual(r['heads'],[cid.hex()]);self.assertEqual(r['revision'],1);self.assertEqual(self.a.read()['note']['title'],'synthetic materialization')
        row=self.db._storage.connection.execute('SELECT record FROM document_apply_events').fetchone()[0];self.assertNotIn(b'SYNTHETIC-NOT-A-CRDT',row);self.assertTrue(self.db.audit()['valid'])
    def test_apply_descendant_collects_ancestors(self):
        e1,c1=self.saved();e2,c2=self.saved(2,sequence=2,previous=e1,deps=[c1]);r=self.call([e2]);self.assertEqual(r['heads'],[c2.hex()]);self.assertEqual(self.nums()['document_inputs'],2)
    def test_union_preserves_concurrent_head(self):
        e1,c1=self.saved();e2,c2=self.saved(2,index=1);self.call([e1]);r=self.call([e2],op=11,expected=1)
        self.assertEqual(r['heads'],sorted([c1.hex(),c2.hex()]));self.assertEqual(self.nums()['document_inputs'],2)
    def test_retry_does_not_reencrypt_or_reinvoke_core(self):
        e,_=self.saved();r=self.call([e]);calls=self.port.calls;n=self.nums();again=self.call([e]);self.assertEqual(r,again);self.assertEqual(self.port.calls,calls);self.assertEqual(self.nums(),n)
    def test_retry_wrong_target_refused(self):
        e,_=self.saved();self.call([e]);self.deny('OPERATION_CONFLICT',lambda:self.call([h('other')]))
    def test_retry_wrong_revision_refused(self):
        e,_=self.saved();self.call([e]);self.deny('OPERATION_CONFLICT',lambda:self.call([e],expected=1))
    def test_stale_expected_revision(self):
        e,_=self.saved();self.call([e]);self.deny('STALE_FRONTIER',lambda:self.call([e],op=11))
    def test_noop_new_operation_refused(self):
        e,_=self.saved();self.call([e]);self.deny('NO_NEW_CHANGES',lambda:self.call([e],op=11,expected=1))
    def test_prepare_is_not_applied(self):
        e,_=self.saved();self.a.prepare(b'p'*16,(e,),expected_revision=0);self.assertEqual(self.nums()['document_apply_events'],0);self.assertEqual(self.nums()['document_apply_nonces'],1)
    def test_new_operation_rejects_after_authority_change(self):
        e,_=self.saved();p=self.a.prepare(b'p'*16,(e,),expected_revision=0);self.same_epoch();self.deny('OWNER_STATE_CHANGED',lambda:self.a.commit(p));self.assertEqual(self.nums()['document_apply_events'],0)
    def test_authority_changes_during_core(self):
        e,_=self.saved();self.port.hook=self.same_epoch;self.deny('OWNER_STATE_CHANGED',lambda:self.call([e]))
    def test_epoch_change_prevents_read(self):
        e,_=self.saved();self.call([e]);self.next_epoch();self.deny('EPOCH_CHANGED',lambda:self.a.read())
    def test_core_change_after_prepare(self):
        e,_=self.saved();p=self.a.prepare(b'p'*16,(e,),expected_revision=0);self.port.identity['digest']='b'*64;self.deny('CORE_IDENTITY_CHANGED',lambda:self.a.commit(p))
    def test_two_preparations_only_first_can_commit(self):
        e,_=self.saved();p=self.a.prepare(b'p'*16,(e,),expected_revision=0);q=self.a.prepare(b'q'*16,(e,),expected_revision=0)
        self.a.commit(p);self.deny('STALE_FRONTIER',lambda:self.a.commit(q))
    def test_reopen_requires_authority_reactivation(self):
        e,_=self.saved();self.call([e]);pin=self.a.pin();self.reopen();a=self.make(expected_pin=pin)
        self.deny('AUTHORITY_NOT_ACTIVE',lambda:a.read());self.db.reactivate(self.s.space,self.s.devices[0]['secret']);self.assertEqual(a.read()['revision'],1)
    def test_wrong_local_key_refused(self):
        e,_=self.saved();self.call([e]);a=self.Applier(self.db,self.port,self.s.devices[0]['cert'],h('wrong'),app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'),allow_contract_double=True)
        self.deny('MATERIALIZATION_INVALID',lambda:a.read())
    def test_event_ciphertext_corruption_refused(self):
        e,_=self.saved();self.call([e]);c=self.db._storage.connection;c.execute("UPDATE document_apply_events SET record=zeroblob(length(record))")
        self.deny('APPLICATION_CORRUPT',lambda:self.a.read())
    def test_missing_frontier_refused(self):
        e,_=self.saved();self.call([e]);self.db._storage.connection.execute('DELETE FROM document_frontiers');self.deny('APPLICATION_CORRUPT',lambda:self.a.read())
    def test_missing_input_refused(self):
        e,_=self.saved();self.call([e]);self.db._storage.connection.execute('DELETE FROM document_inputs');self.deny('APPLICATION_CORRUPT',lambda:self.a.read())
    def test_nonce_record_missing_refused(self):
        e,_=self.saved();self.call([e]);self.db._storage.connection.execute('DELETE FROM document_apply_nonces');self.deny('APPLICATION_CORRUPT',lambda:self.a.read())
    def test_extra_schema_refused(self):
        self.db._storage.connection.execute('CREATE TABLE alien(x INTEGER)');self.deny('APPLICATION_CORRUPT',lambda:self.a.read())
    def test_pin_rejects_missing_known_history(self):
        e,_=self.saved();self.call([e]);pin=self.a.pin();pin['revision']+=1;self.deny('APPLICATION_PIN_MISMATCH',lambda:self.make(expected_pin=pin))
    def test_retry_old_operation_after_new_frontier(self):
        e1,c1=self.saved();r=self.call([e1]);e2,c2=self.saved(2,index=1);self.call([e2],op=11,expected=1)
        self.assertEqual(self.call([e1]),r);self.assertEqual(self.a.read()['revision'],2)
    def test_current_application_mode_cannot_mix_synthetic(self):
        e,_=self.saved();self.call([e]);a=self.make(allow_contract_double=False);self.deny('SYNTHETIC_APPLICATION',lambda:a.read())
