import copy,importlib,importlib.util,unittest
from fetch_support import LocalFixture
from process_fixture import h
from par_crypto import objects
from product.wp09.par_secure_fetch import FetchError

class ControllerTests(LocalFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.assertIsNotNone(importlib.util.find_spec('product.runtime_read.fetch'),'fetch application controller missing')
        self.mod=importlib.import_module('product.runtime_read.fetch');self.a,self.b=self.remote.chain();self.target=objects.envelope_id(self.b[0]);self.local.box.receive(*self.b)
        self.c=self.make()
    def make(self,**kw):return self.mod.FetchApplicationController(self.make_plan(),self.local.source,[self.target],lambda:self.gen[0],**kw)
    def test_read_only_waiting_view(self):
        before=self.local.box.pin();v=self.c.observe();self.assertEqual(v['records'][0]['state'],'WAITING_DEPENDENCIES')
        self.assertEqual(v['records'][0]['missingInner'],[h('inner:a').hex()]);self.assertFalse(v['applied']);self.assertEqual(self.local.box.pin(),before)
    def test_pin_binds_plan_targets_scope_and_generations(self):
        p=self.c.pin();self.assertEqual(p['planDigest'],self.make_plan().digest);self.assertEqual(p['connectionGeneration'],'9');self.assertEqual(len(p['targetDigest']),64)
        self.assertEqual(p['scope']['controlHead'],self.local.source.scope[5].hex())
    def test_monotone_sequence_and_revision(self):
        a=self.c.observe();b=self.c.observe();self.assertEqual(int(b['sequence']),int(a['sequence'])+1);self.assertNotEqual(a['revision'],b['revision'])
    def test_observation_is_owned(self):
        a=self.c.observe();a['records'].clear();self.assertEqual(len(self.c.observe()['records']),1)
    def test_validate_unready_does_not_apply(self):
        a=self.c.observe();v=self.c.validate(expected_revision=a['revision']);self.assertEqual(v['records'][0]['validation']['state'],'WAITING_DEPENDENCIES');self.assertFalse(v['applied'])
    def test_ready_core_absence_is_blocked(self):
        self.local.box.receive(*self.a);a=self.c.observe();before=self.local.db._storage.connection.total_changes
        v=self.c.validate(expected_revision=a['revision']);self.assertEqual(v['records'][0]['validation']['state'],'CORE_BLOCKED');self.assertEqual(v['records'][0]['validation']['reason'],'CORE_UNAVAILABLE')
        self.assertEqual(before,self.local.db._storage.connection.total_changes)
    def test_old_observation_cannot_trigger_command(self):
        a=self.c.observe();self.c.observe()
        with self.assertRaisesRegex(FetchError,'STALE_OBSERVATION'):self.c.validate(expected_revision=a['revision'])
    def test_candidate_added_after_observation_requires_refresh(self):
        a=self.c.observe();self.local.box.receive(*self.a)
        with self.assertRaisesRegex(FetchError,'LOCAL_VIEW_CHANGED'):self.c.validate(expected_revision=a['revision'])
    def test_generation_changed_rejects_view(self):
        self.gen[0]=10
        with self.assertRaisesRegex(FetchError,'STALE_GENERATION'):self.c.observe()
    def test_close_rejects_view(self):
        self.c.close()
        with self.assertRaisesRegex(FetchError,'CONTROLLER_CLOSED'):self.c.observe()
    def test_apply_unavailable_keeps_original_id(self):
        self.local.box.receive(*self.a);a=self.c.observe();v=self.c.apply(b'z'*16,expected_revision=0,expected_observation=a['revision'])
        self.assertEqual(v['operation']['id'],(b'z'*16).hex());self.assertEqual(v['operation']['state'],'CORE_BLOCKED');self.assertFalse(v['applied'])
    def test_apply_bad_id_rejected_before_state_change(self):
        a=self.c.observe()
        with self.assertRaises(FetchError):self.c.apply(b'z',expected_revision=0,expected_observation=a['revision'])
        self.assertIsNone(self.c.observe()['operation']['id'])
    def test_validation_not_reused_after_new_candidate(self):
        a=self.c.observe();self.c.validate(expected_revision=a['revision']);self.local.box.receive(*self.a)
        self.assertIsNone(self.c.observe()['records'][0]['validation'])
    def test_wrong_source_rejected(self):
        with self.assertRaises(FetchError):self.mod.FetchApplicationController(self.make_plan(),self.remote.source,[self.target],lambda:9)
    def test_targets_copied(self):
        roots=[self.target];c=self.mod.FetchApplicationController(self.make_plan(),self.local.source,roots,lambda:9);roots[0]=h('other')
        self.assertEqual(c.observe()['records'][0]['envelopeId'],self.target.hex())
    def test_duplicate_targets_rejected(self):
        with self.assertRaises(FetchError):self.mod.FetchApplicationController(self.make_plan(),self.local.source,[self.target]*2,lambda:9)
    def test_no_payload_or_key_in_view(self):
        import json
        out=json.dumps(self.c.observe());self.assertNotIn('PUBLIC OPAQUE',out);self.assertNotIn('certificate',out.lower());self.assertNotIn('plaintext',out.lower())
    def test_contract_double_not_promoted(self):
        class Fake:
            identity={'kind':'contract-test-double'}
            def validate(self,req):raise AssertionError('must not call a double')
        self.local.box.receive(*self.a);c=self.make(core=Fake());a=c.observe();v=c.validate(expected_revision=a['revision'])
        self.assertEqual(v['records'][0]['validation']['reason'],'CORE_NOT_REAL');self.assertFalse(v['innerValidated'])
    def test_validation_generation_change_not_published(self):
        self.local.box.receive(*self.a);original=self.local.box.validate
        def changed(*a,**k):result=original(*a,**k);self.gen[0]=10;return result
        self.local.box.validate=changed;a=self.c.observe()
        with self.assertRaisesRegex(FetchError,'STALE_GENERATION'):self.c.validate(expected_revision=a['revision'])
