"""Real authenticated application Store, explicitly synthetic note contents."""
import copy
import importlib.util
import json
import threading
from unittest.mock import patch
from apply_support import ApplyTest, h


class ApplicationObservationTests(ApplyTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.runtime_read.application'),
                             'schema4 observation adapter is not implemented')
        from product.runtime_read.application import ApplicationObserver
        self.Observer = ApplicationObserver
        self.reader = self.Observer(self.a)

    def applied_candidate(self):
        eid, _ = self.saved()
        result = self.call([eid])
        return result

    def test_empty_scope_is_not_a_deleted_document(self):
        r = self.reader.observe()
        self.assertEqual(r['application']['state'], 'EMPTY')
        self.assertIsNone(r['application']['note'])
        self.assertFalse(r['catalogComplete'])
        self.assertEqual(r['operation']['state'], 'NOT_QUERIED')

    def test_candidate_is_persisted_but_never_exposes_plaintext(self):
        self.applied_candidate()
        self.port.materialize = lambda _: self.fail('candidate observation must not run core')
        r = self.reader.observe((10).to_bytes(16, 'big'))
        self.assertEqual(r['application']['state'], 'CANDIDATE_ONLY')
        self.assertEqual(r['operation']['state'], 'OBSERVED_CANDIDATE')
        self.assertIsNone(r['application']['note'])
        self.assertNotIn('SYNTHETIC-NOT-A-CRDT', json.dumps(r))
        self.assertFalse(r['application']['applied'])
        self.assertFalse(r['application']['innerValidated'])
        self.assertFalse(r['capabilities']['sharedCommit'])

    def test_operation_not_observed_is_not_failed(self):
        self.applied_candidate()
        r = self.reader.observe(b'?' * 16)
        self.assertEqual(r['operation']['state'], 'NOT_OBSERVED')
        self.assertIsNone(r['operation']['eventDigest'])

    def test_query_needs_exact_bytes_not_mutable_or_text(self):
        for op in (True, 1, '00' * 16, b'', b'a' * 17, bytearray(16)):
            self.deny('INVALID_INPUT', lambda: self.reader.observe(op))

    def test_observation_does_not_write_or_sign_or_reserve_nonce(self):
        self.applied_candidate()
        before = self.db._storage.connection.total_changes
        nums = self.nums()
        with patch.object(self.p, 'sign', side_effect=AssertionError('must not sign')):
            a = self.reader.observe()
            b = self.reader.observe()
        self.assertEqual(before, self.db._storage.connection.total_changes)
        self.assertEqual(nums, self.nums())
        self.assertEqual(int(b['sequence']), int(a['sequence']) + 1)
        self.assertNotEqual(a['revision'], b['revision'])

    def test_wrong_local_key_cannot_validate_even_candidate(self):
        self.applied_candidate()
        self.a._key = b'x' * 32
        self.deny('APPLICATION_READ_FAILED', lambda: self.reader.observe())

    def test_tampered_aead_is_not_a_candidate_observation(self):
        self.applied_candidate()
        self.db._storage.connection.execute('UPDATE document_apply_events SET record_digest=?', (b'x' * 32,))
        self.deny('APPLICATION_READ_FAILED', lambda: self.reader.observe())

    def test_input_record_missing_is_not_empty(self):
        self.applied_candidate()
        self.db._storage.connection.execute('DELETE FROM document_inputs')
        self.deny('APPLICATION_READ_FAILED', lambda: self.reader.observe())

    def test_frontier_missing_is_not_empty(self):
        self.applied_candidate()
        self.db._storage.connection.execute('DELETE FROM document_frontiers')
        self.deny('APPLICATION_READ_FAILED', lambda: self.reader.observe())

    def test_result_mutation_does_not_mutate_reader(self):
        self.applied_candidate()
        r = self.reader.observe()
        r['application']['heads'].clear()
        self.assertTrue(self.reader.observe()['application']['heads'])

    def test_reader_close_is_idempotent_but_use_is_forbidden(self):
        self.reader.close()
        self.reader.close()
        self.deny('OBSERVER_CLOSED', lambda: self.reader.observe())

    def test_other_thread_is_refused_and_owner_still_works(self):
        found = []
        def run():
            try: self.reader.observe()
            except Exception as e: found.append(e.code)
        t = threading.Thread(target=run); t.start(); t.join(3)
        self.assertEqual(found, ['WRONG_OWNER'])
        self.assertEqual(self.reader.observe()['application']['state'], 'EMPTY')

    def test_reader_restart_has_new_stream(self):
        self.assertNotEqual(self.reader.pin()['streamId'], self.Observer(self.a).pin()['streamId'])

    def test_invalid_engine_pin_is_rejected(self):
        for p in ({}, self.port.identity, {'name':'@automerge/automerge', 'version':'3.4.1', 'kind':'automerge', 'digest':'bad'}):
            self.deny('ENGINE_PIN_INVALID', lambda: self.Observer(self.a, expected_engine=p))

    def test_reentrant_observe_during_decrypt_is_refused(self):
        self.applied_candidate()
        original = self.p.open
        def hook(*args):
            self.deny('REENTRANT_OPERATION', lambda: self.reader.observe())
            return original(*args)
        with patch.object(self.p, 'open', side_effect=hook): self.reader.observe()

    def test_write_during_decrypt_invalidates_observation(self):
        self.applied_candidate()
        original = self.p.open
        once = []
        def hook(*args):
            if not once:
                once.append(True)
                c = self.db._storage.connection
                c.execute('UPDATE document_frontiers SET heads=heads')
            return original(*args)
        with patch.object(self.p, 'open', side_effect=hook):
            self.deny('OBSERVATION_CHANGED', lambda: self.reader.observe())

    def test_authority_change_during_decrypt_is_refused(self):
        self.applied_candidate()
        original = self.p.open
        def hook(*args):
            self.db._failed[self.s.space] = 'test'
            return original(*args)
        with patch.object(self.p, 'open', side_effect=hook):
            self.deny('APPLICATION_READ_FAILED', lambda: self.reader.observe())

    def test_core_validated_label_without_owner_pin_does_not_reveal_note(self):
        # Controlled fixture doubles an actual-kind port. It is NOT actual Automerge.
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        r = self.reader.observe((10).to_bytes(16, 'big'))
        self.assertEqual(r['application']['state'], 'CORE_RECHECK_REQUIRED')
        self.assertIsNone(r['application']['note'])
        self.assertFalse(r['application']['innerValidated'])
        self.assertEqual(r['operation']['state'], 'OBSERVED_APPLICATION_RECORD')

    def test_pinned_replay_contract_on_explicit_simulated_port(self):
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        r = self.Observer(self.a, expected_engine=self.port.identity).observe()
        self.assertEqual(r['application']['state'], 'VALIDATED_LOCAL_VIEW')
        self.assertEqual(r['application']['note']['title'], 'synthetic materialization')
        self.assertFalse(r['capabilities']['sharedCommit'])
        self.assertFalse(r['productQualified'])

    def test_core_replay_note_mismatch_is_refused(self):
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        self.port.mutate = lambda r: r['note'].update(body='forged')
        self.deny('APPLICATION_READ_FAILED', lambda: self.Observer(self.a, expected_engine=self.port.identity).observe())

    def test_engine_change_is_refused_before_replay(self):
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        reader = self.Observer(self.a, expected_engine=self.port.identity)
        self.port.identity['digest'] = 'e' * 64
        self.deny('APPLICATION_READ_FAILED', lambda: reader.observe())

    def test_core_unavailable_returns_no_plaintext(self):
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        reader = self.Observer(self.a, expected_engine=self.port.identity)
        from product.wp04.contracts import SharedChangeError
        def gone(_): raise SharedChangeError('CORE_UNAVAILABLE')
        self.port.materialize = gone
        r = reader.observe()
        self.assertEqual(r['application']['state'], 'CORE_RECHECK_REQUIRED')
        self.assertIsNone(r['application']['note'])

    def test_history_query_is_not_frontier_query(self):
        one, inner = self.saved(); self.call([one])
        two, _ = self.saved(op=2, sequence=2, previous=one, deps=(inner,))
        self.call([two], op=11, expected=1)
        r = self.reader.observe((10).to_bytes(16,'big'))
        self.assertEqual(r['application']['revision'], 2)
        self.assertEqual(r['operation']['revision'], 1)
        self.assertEqual(r['operation']['state'], 'OBSERVED_CANDIDATE')

    def test_candidate_never_calls_core_even_with_actual_pin(self):
        self.applied_candidate()
        pin = dict(self.port.identity, kind='automerge')
        r = self.Observer(self.a, expected_engine=pin).observe()
        self.assertEqual(r['application']['state'], 'CANDIDATE_ONLY')

    def test_reader_survives_nonce_reservation_without_application(self):
        eid,_ = self.saved()
        self.a.prepare(b'?'*16,(eid,),expected_revision=0)
        r=self.reader.observe(b'?'*16)
        self.assertEqual(r['application']['state'],'EMPTY')
        self.assertEqual(r['operation']['state'],'NOT_OBSERVED')

    def test_expected_engine_pin_is_copied(self):
        self.port.identity['kind'] = 'automerge'
        self.applied_candidate()
        pin = dict(self.port.identity)
        reader = self.Observer(self.a, expected_engine=pin)
        pin['digest']='a'*64
        self.assertEqual(reader.observe()['application']['state'],'VALIDATED_LOCAL_VIEW')

    def test_multiple_application_replay_reconstructs_original_order(self):
        self.port.identity['kind']='automerge'
        first,cid=self.saved();self.call([first])
        second,_=self.saved(op=2,sequence=2,previous=first,deps=(cid,))
        self.call([second],op=11,expected=1)
        r=self.Observer(self.a,expected_engine=self.port.identity).observe()
        self.assertEqual(r['application']['revision'],2)
        self.assertEqual(r['application']['inputCount'],2)
        self.assertTrue(r['application']['innerValidated'])

    def test_independent_authors_replay_exact_union(self):
        self.port.identity['kind']='automerge'
        first,_=self.saved();self.call([first])
        second,_=self.saved(op=2,index=1)
        self.call([second],op=11,expected=1)
        r=self.Observer(self.a,expected_engine=self.port.identity).observe()
        self.assertEqual(len(r['application']['heads']),2)

    def test_candidate_input_is_reverified_not_just_a_digest(self):
        self.applied_candidate()
        original=self.a._record
        calls=[]
        def record(*args,**kw):
            calls.append(args[0]);return original(*args,**kw)
        with patch.object(self.a,'_record',side_effect=record):self.reader.observe()
        self.assertEqual(len(calls),1)

    def test_fixed_scope_mutation_rejected(self):
        self.a._scope['document']='f'*64
        self.deny('SCOPE_MISMATCH',lambda:self.reader.observe())

    def test_sequence_overflow_before_emit(self):
        self.reader._sequence=2**64-1
        self.deny('SEQUENCE_EXHAUSTED',lambda:self.reader.observe())

    def test_epoch_change_does_not_return_old_note(self):
        self.applied_candidate();self.next_epoch()
        self.deny('APPLICATION_READ_FAILED',lambda:self.reader.observe())

    def test_wrong_certificate_operation_hidden(self):
        eid,_=self.saved()
        other=self.Applier(self.db,self.port,self.s.devices[1]['cert'],h('local-apply-secret'),
             app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'),allow_contract_double=True)
        other.apply((10).to_bytes(16,'big'),(eid,),expected_revision=0)
        self.assertEqual(self.reader.observe((10).to_bytes(16,'big'))['operation']['state'],'NOT_OBSERVED')

    def test_missing_core_with_pin_is_blocked_not_visible(self):
        self.port.identity['kind']='automerge';self.applied_candidate()
        reader=self.Observer(self.a,expected_engine=self.port.identity)
        self.a._core=None
        r=reader.observe()
        self.assertEqual(r['application']['state'],'CORE_RECHECK_REQUIRED')

    def test_reopened_application_no_core_candidates_remain_hidden(self):
        self.applied_candidate();self.a.close();self.reopen();self.activate()
        self.a=self.make();r=self.Observer(self.a).observe((10).to_bytes(16,'big'))
        self.assertEqual(r['application']['state'],'CANDIDATE_ONLY')
        self.assertIsNone(r['application']['note'])

    def test_pin_binding_includes_expected_engine_digest(self):
        self.assertIsNone(self.reader.pin()['engineDigest'])
        pin=dict(self.port.identity,kind='automerge')
        self.assertEqual(self.Observer(self.a,expected_engine=pin).pin()['engineDigest'],pin['digest'])

    def test_previously_observed_frontier_cannot_disappear(self):
        eid,_=self.saved();writer=self.make();writer.apply((10).to_bytes(16,'big'),(eid,),expected_revision=0)
        self.reader.observe()
        c=self.db._storage.connection
        for table in ('document_frontiers','document_apply_events','document_inputs','document_apply_nonces'):c.execute('DELETE FROM '+table)
        self.deny('APPLICATION_READ_FAILED',lambda:self.reader.observe())

    def test_candidate_inbox_only_signatures_are_rechecked(self):
        self.applied_candidate()
        def bad(*args,**kwargs):
            from product.wp04.application import ApplicationError
            raise ApplicationError('INPUT_VERIFICATION_FAILED')
        with patch.object(self.a,'_record',side_effect=bad):
            self.deny('APPLICATION_READ_FAILED',lambda:self.reader.observe())

    def test_engine_changes_during_replay_is_refused(self):
        self.port.identity['kind']='automerge';self.applied_candidate()
        reader=self.Observer(self.a,expected_engine=self.port.identity)
        self.port.hook=lambda:self.port.identity.update(digest='e'*64)
        self.deny('APPLICATION_READ_FAILED',lambda:reader.observe())
