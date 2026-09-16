import dataclasses,threading
from apply_support import ApplyTest,h

class ContractTests(ApplyTest):
    def test_default_rejects_double_before_nonce(self):
        e,_=self.saved();a=self.make(allow_contract_double=False)
        self.deny('CORE_NOT_REAL',lambda:a.prepare(b'o'*16,(e,),expected_revision=0))
        self.assertEqual(self.nums()['document_apply_nonces'],0)
    def test_false_report_never_promotes_applied(self):
        e,_=self.saved();r=self.call([e]);self.assertFalse(r['applied']);self.assertFalse(r['innerValidated']);self.assertTrue(r['candidatePersisted'])
        self.assertEqual(self.a.read()['phase'],'CANDIDATE_ONLY');self.assertEqual(self.db._storage.connection.execute('SELECT state FROM envelopes').fetchone()[0],'pending')
    def test_empty_targets_refused(self):self.deny('INVALID_INPUT',lambda:self.call([]))
    def test_duplicate_targets_refused(self):
        e,_=self.saved();self.deny('INVALID_INPUT',lambda:self.call([e,e]))
    def test_invalid_operation_id(self):self.deny('INVALID_INPUT',lambda:self.a.prepare(b'o',(h('x'),),expected_revision=0))
    def test_boolean_revision_refused(self):self.deny('INVALID_INPUT',lambda:self.a.prepare(b'o'*16,(h('x'),),expected_revision=True))
    def test_absent_input_refused(self):self.deny('DEPENDENCIES_MISSING',lambda:self.call([h('absent')]))
    def test_wrong_document_refused(self):
        e,_=self.saved();a=self.make(document_id=h('other'));self.deny('DEPENDENCIES_MISSING',lambda:a.apply(b'a'*16,(e,),expected_revision=0))
    def test_wrong_schema_refused(self):
        e,_=self.saved();a=self.make(schema_id=h('other'));self.deny('SCHEMA_MISMATCH',lambda:a.apply(b'a'*16,(e,),expected_revision=0))
    def test_missing_dependency_before_core(self):
        e,_=self.saved(deps=[h('missing')]);self.deny('DEPENDENCIES_MISSING',lambda:self.call([e]));self.assertEqual(self.port.calls,0)
    def test_core_missing_does_not_write(self):
        e,_=self.saved();self.a._core=None;self.deny('CORE_UNAVAILABLE',lambda:self.call([e]));self.assertEqual(self.nums()['document_apply_events'],0)
    def test_core_throw_does_not_allocate_nonce(self):
        e,_=self.saved();self.port.hook=lambda:(_ for _ in ()).throw(RuntimeError('engine'))
        self.deny('CORE_FAILURE',lambda:self.call([e]));self.assertEqual(self.nums()['document_apply_nonces'],0)
    def test_core_identity_changed_during_call(self):
        e,_=self.saved();self.port.hook=lambda:self.port.identity.update(digest='e'*64)
        self.deny('CORE_IDENTITY_CHANGED',lambda:self.call([e]))
    def test_report_has_wrong_context(self):
        e,_=self.saved();self.port.mutate=lambda r:r.update(requestDigest='a'*64);self.deny('CORE_CONTEXT_MISMATCH',lambda:self.call([e]))
    def test_report_omits_change(self):
        e,_=self.saved();self.port.mutate=lambda r:r.update(appliedHashes=[]);self.deny('APPLIED_SET_MISMATCH',lambda:self.call([e]))
    def test_report_duplicate_change(self):
        e,cid=self.saved();self.port.mutate=lambda r:r.update(appliedHashes=[cid.hex(),cid.hex()]);self.deny('APPLIED_SET_MISMATCH',lambda:self.call([e]))
    def test_report_wrong_heads(self):
        e,_=self.saved();self.port.mutate=lambda r:r.update(heads=[]);self.deny('FRONTIER_MISMATCH',lambda:self.call([e]))
    def test_report_wrong_actor(self):
        e,_=self.saved();self.port.mutate=lambda r:r['changes'][0].update(actor='a'*64);self.deny('INNER_OUTER_MISMATCH',lambda:self.call([e]))
    def test_report_missing_dependency(self):
        e,_=self.saved();self.port.mutate=lambda r:r.update(missing=['b'*64]);self.deny('DEPENDENCIES_MISSING',lambda:self.call([e]))
    def test_report_invalid_note(self):
        e,_=self.saved();self.port.mutate=lambda r:r['note'].update(body=12);self.deny('CORE_REPORT_INVALID',lambda:self.call([e]))
    def test_owner_thread_enforced(self):
        seen=[]
        def f():
            try:self.a.read()
            except Exception as exc:seen.append(getattr(exc,'code',None))
        t=threading.Thread(target=f);t.start();t.join();self.assertEqual(seen,['WRONG_OWNER'])
    def test_reentry_rejected(self):
        e,_=self.saved();self.port.hook=lambda:self.a.read();self.deny('REENTRANT_OPERATION',lambda:self.call([e]))
    def test_closed_applier_rejected(self):self.a.close();self.deny('CLOSED',lambda:self.a.read())
    def test_prepared_from_other_instance_rejected(self):
        e,_=self.saved();p=self.a.prepare(b'o'*16,(e,),expected_revision=0);b=self.make();self.deny('FOREIGN_PREPARED_APPLY',lambda:b.commit(p))
    def test_modified_prepared_rejected(self):
        e,_=self.saved();p=self.a.prepare(b'o'*16,(e,),expected_revision=0)
        self.deny('PREPARED_CHANGED',lambda:self.a.commit(dataclasses.replace(p,ciphertext=p.ciphertext[:-1]+bytes([p.ciphertext[-1]^1]))))
