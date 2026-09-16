"""Explicitly SYNTHETIC materializer contracts. Never real Automerge evidence.

The positive fixture advertises an engine kind only to exercise the pre-existing
application transaction API. This suite is separate from TLS/process coverage.
"""
import asyncio,unittest
from apply_support import ApplyTest,h
from product.wp04.inbox import SyncInbox
from product.wp04.exchange import Source
from par_crypto import objects
from product.wp09.par_secure_fetch import FetchPlan,FetchError
from product.wp09.par_secure_transport import PeerBinding
from product.runtime_read.fetch import FetchApplicationController

class ApplicationDelegationTests(ApplyTest):
    def setUp(self):
        super().setUp();self.gen=[9]
        self.box=SyncInbox.create(self.root.parent/'inbox',self.db,app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'));self.addCleanup(self.box.close)
        _,header,plain,_=self.request();raw=objects.seal_change(self.p,self.s.secret,self.s.devices[0]['seed'],header,plain,h('bridge-nonce')[:24]);self.box.receive(raw,self.s.devices[0]['cert']);self.target=objects.envelope_id(raw)
        d=self.s.devices[0];self.source=Source(self.box,d['cert'],d['seed']);snapshot,descriptors,_=self.source.catalog(d['cert']);self.binding=PeerBinding('owner',d['cert'],self.source.scope,'a'*64,9)
        self.plan=FetchPlan(self.source.scope,snapshot,descriptors,self.binding,self.box.pin()['generation'])
        self.a=self.make(inbox=self.box,allow_contract_double=False)
        self.c=self.controller(self.a)
    def controller(self,a):return FetchApplicationController(self.plan,self.source,[self.target],lambda:self.gen[0],application=a)
    def simulate_identity(self):self.port.identity['kind']='automerge' # SIMULATION ONLY
    def run_apply(self):
        v=self.c.observe();return self.c.apply(b'o'*16,expected_revision=0,expected_observation=v['revision'])
    def committed_unknown(self):
        self.simulate_identity()
        def fault(stage):
            if stage=='apply.after_commit':raise RuntimeError('simulated response loss')
        self.a.observer=fault;v=self.run_apply();self.assertEqual(v['operation']['state'],'OUTCOME_UNKNOWN');return v
    def test_contract_double_blocked_before_nonce(self):
        v=self.run_apply();self.assertEqual(v['operation']['state'],'CORE_BLOCKED');self.assertEqual(v['operation']['reason'],'CORE_NOT_REAL');self.assertEqual(self.nums()['document_apply_nonces'],0);self.assertEqual(self.port.calls,0)
    def test_synthetic_delegation_reuses_existing_atomic_store(self):
        self.simulate_identity();v=self.run_apply();self.assertEqual(self.nums()['document_apply_events'],1);self.assertEqual(v['operation']['state'],'OBSERVED_APPLICATION_RECORD');self.assertFalse(v['applied']);self.assertEqual(self.count('envelopes'),0)
    def test_optional_application_must_not_allow_doubles(self):
        with self.assertRaisesRegex(FetchError,'APPLICATION_BINDING'):self.controller(self.make(inbox=self.box,allow_contract_double=True))
    def test_commit_response_loss_retains_original_id(self):
        v=self.committed_unknown();self.assertEqual(self.nums()['document_apply_events'],1);self.assertEqual(v['operation']['id'],(b'o'*16).hex())
        with self.assertRaisesRegex(FetchError,'INQUIRY_REQUIRED'):self.c.apply(b'p'*16,expected_revision=0,expected_observation=v['revision'])
    def test_unknown_inquiry_must_use_original_id(self):
        v=self.committed_unknown()
        with self.assertRaisesRegex(FetchError,'ORIGINAL_OPERATION_REQUIRED'):self.c.inquire(b'p'*16,expected_revision=0,expected_observation=v['revision'])
        self.assertEqual(self.c.operation['id'],(b'o'*16).hex())
    def test_unknown_inquiry_must_keep_original_expected_revision(self):
        v=self.committed_unknown()
        with self.assertRaisesRegex(FetchError,'ORIGINAL_OPERATION_REQUIRED'):self.c.inquire(b'o'*16,expected_revision=1,expected_observation=v['revision'])
    def test_failed_inquiry_does_not_unlock_replay(self):
        v=self.committed_unknown();v=self.c.inquire(b'o'*16,expected_revision=0,expected_observation=v['revision']);self.assertEqual(v['operation']['state'],'INQUIRY_FAILED')
        with self.assertRaisesRegex(FetchError,'INQUIRY_REQUIRED'):self.c.apply(b'p'*16,expected_revision=0,expected_observation=v['revision'])
    def test_reopened_application_inquires_without_materializing(self):
        self.committed_unknown();calls=self.port.calls
        fresh=self.make(inbox=self.box,allow_contract_double=False);c=self.controller(fresh);v=c.observe();v=c.inquire(b'o'*16,expected_revision=0,expected_observation=v['revision'])
        self.assertEqual(v['operation']['state'],'OBSERVED_APPLICATION_RECORD');self.assertEqual(self.port.calls,calls);self.assertEqual(self.nums()['document_apply_events'],1);self.assertFalse(v['applied'])
    def test_cancellation_is_propagated_with_uncertain_intent(self):
        self.simulate_identity()
        def cancel(*a,**k):raise asyncio.CancelledError
        self.a.apply=cancel;v=self.c.observe()
        with self.assertRaises(asyncio.CancelledError):self.c.apply(b'o'*16,expected_revision=0,expected_observation=v['revision'])
        self.assertEqual(self.c.operation['state'],'OUTCOME_UNKNOWN');self.assertEqual(self.c.operation['id'],(b'o'*16).hex())
    def test_actual_core_absence_does_not_write(self):
        self.a._core=None;v=self.run_apply();self.assertEqual(v['operation']['reason'],'CORE_UNAVAILABLE');self.assertEqual(self.nums()['document_apply_nonces'],0)
    def test_not_observed_inquiry_does_not_unlock_uncertain_intent(self):
        v=self.committed_unknown();self.a.inquire=lambda *a,**k:None
        v=self.c.inquire(b'o'*16,expected_revision=0,expected_observation=v['revision'])
        self.assertEqual(v['operation']['state'],'NOT_OBSERVED')
        with self.assertRaisesRegex(FetchError,'INQUIRY_REQUIRED'):self.c.apply(b'p'*16,expected_revision=0,expected_observation=v['revision'])
    def test_failure_after_delegation_is_unknown_even_if_named_core_failure(self):
        from product.wp04.application import ApplicationError
        self.simulate_identity()
        def fail(*a,**k):raise ApplicationError('CORE_TIMEOUT')
        self.a.apply=fail;v=self.run_apply();self.assertEqual(v['operation']['state'],'OUTCOME_UNKNOWN')
    def test_failed_validation_drops_cached_validation(self):
        self.c.observe();self.c._validation={self.target:{'state':'SEMANTICALLY_VALIDATED_PENDING','reason':None}}
        self.c._validation_revision=self.c._guard()
        def fail(*a,**k):raise RuntimeError('synthetic revalidation failure')
        original=self.box.validate;self.box.validate=fail;v=self.c.observe()
        try:
            with self.assertRaises(RuntimeError):self.c.validate(expected_revision=v['revision'])
        finally:self.box.validate=original
        self.assertIsNone(self.c.observe()['records'][0]['validation'])
