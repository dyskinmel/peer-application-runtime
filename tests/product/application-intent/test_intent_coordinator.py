"""Transaction delegation fixtures are SYNTHETIC, never actual Automerge evidence."""
import asyncio,dataclasses,importlib,unittest
from apply_support import ApplyTest,h
from product.wp04.inbox import SyncInbox
from product.wp04.exchange import Source
from product.wp09.par_secure_transport import PeerBinding
from product.wp09.par_secure_fetch import FetchPlan
from product.runtime_read.fetch import FetchApplicationController
from par_crypto import objects

class IntentCoordinatorTests(ApplyTest):
    def setUp(self):
        super().setUp();self.m=importlib.import_module('product.wp09.par_application_intent')
        self.assertTrue(hasattr(self.m,'DurableApplication'),'durable application coordinator missing')
        self.box=SyncInbox.create(self.root.parent/'inbox',self.db,app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'));self.addCleanup(self.box.close)
        _,hdr,plain,_=self.request();raw=objects.seal_change(self.p,self.s.secret,self.s.devices[0]['seed'],hdr,plain,h('intent-nonce')[:24]);self.box.receive(raw,self.s.devices[0]['cert']);self.target=objects.envelope_id(raw)
        d=self.s.devices[0];self.source=Source(self.box,d['cert'],d['seed']);snapshot,ds,_=self.source.catalog(d['cert']);self.gen=[9]
        self.plan=FetchPlan(self.source.scope,snapshot,ds,PeerBinding('owner',d['cert'],self.source.scope,'a'*64,9),self.box.pin()['generation'])
        self.app=self.make(inbox=self.box,allow_contract_double=False)
        self.c=self.controller();binding=self.m.DurableApplication.binding(self.c)
        self.j=self.m.IntentJournal.create(self.root.parent/'intents',binding);self.addCleanup(self.j.close)
        self.d=self.m.DurableApplication(self.j,self.c)
    def controller(self,app=None):
        return FetchApplicationController(self.plan,self.source,[self.target],lambda:self.gen[0],application=app or self.app)
    def prepare(self):
        v=self.c.observe();return self.d.prepare(b'o'*16,expected_revision=0,expected_observation=v['revision'])
    def execute(self,**kw):
        v=self.c.observe();return self.d.execute(self.j.current.digest,expected_observation=v['revision'],**kw)
    def simulate(self):self.port.identity['kind']='automerge' # SIMULATED identity, not real CRDT.
    def reopen(self):
        pin=self.j.pin();self.j.close();self.j=self.m.IntentJournal.open(self.root.parent/'intents',self.m.DurableApplication.binding(self.c),expected_pin=pin);self.addCleanup(self.j.close)
        self.app=self.make(inbox=self.box,allow_contract_double=False);self.c=self.controller();self.d=self.m.DurableApplication(self.j,self.c)
    def test_prepare_records_original_without_nonce(self):
        v=self.prepare();self.assertEqual(v['state'],'PREPARED');self.assertEqual(self.nums()['document_apply_nonces'],0);self.assertEqual(self.port.calls,0)
    def test_default_core_blocks_before_dispatch(self):
        self.prepare();v=self.execute();self.assertEqual(v['operationState'],'CORE_BLOCKED');self.assertEqual(self.j.status()['state'],'PREPARED');self.assertEqual(self.nums()['document_apply_nonces'],0)
    def test_absent_core_blocks_without_apply(self):
        self.app._core=None;self.prepare();v=self.execute();self.assertEqual(v['reason'],'CORE_UNAVAILABLE');self.assertEqual(self.nums()['document_apply_events'],0)
    def test_synthetic_transaction_after_dispatch_only(self):
        self.simulate();self.prepare();stages=[]
        def witness(stage):
            if stage=='apply.nonce_after_commit':stages.append(self.j.status()['state'])
        self.app.observer=witness;v=self.execute();self.assertEqual(stages,['DISPATCHED']);self.assertEqual(v['state'],'OBSERVED');self.assertEqual(self.nums()['document_apply_events'],1);self.assertFalse(v['applied'])
    def test_commit_response_loss_reopen_original_inquiry(self):
        self.simulate();self.prepare()
        def crash(stage):
            if stage=='apply.after_commit':raise RuntimeError('response lost')
        self.app.observer=crash;v=self.execute();self.assertEqual(v['operationState'],'OUTCOME_UNKNOWN');self.assertEqual(self.nums()['document_apply_events'],1)
        self.reopen();calls=self.port.calls;v=self.d.inquire(self.j.current.digest)
        self.assertEqual(v['state'],'OBSERVED');self.assertEqual(calls,self.port.calls);self.assertEqual(self.nums()['document_apply_events'],1)
    def test_prepared_reopen_can_explicitly_execute(self):
        self.simulate();self.prepare();self.reopen();v=self.execute();self.assertEqual(v['state'],'OBSERVED')
    def test_dispatch_without_apply_requires_inquiry_forever(self):
        self.simulate();self.prepare();self.j.dispatch(self.j.current.digest);self.reopen();v=self.d.inquire(self.j.current.digest)
        self.assertEqual(v['operationState'],'NOT_OBSERVED');self.assertEqual(v['state'],'DISPATCHED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):self.execute()
        self.assertEqual(self.port.calls,0)
    def test_wrong_digest_inquiry_is_not_sent(self):
        self.prepare()
        with self.assertRaisesRegex(Exception,'INTENT_PIN'):self.d.inquire('0'*64)
    def test_new_id_cannot_bypass_unknown(self):
        self.prepare();self.j.dispatch(self.j.current.digest);v=self.c.observe()
        with self.assertRaisesRegex(Exception,'ACTIVE_INTENT'):self.d.prepare(b'p'*16,expected_revision=0,expected_observation=v['revision'])
    def test_changed_expected_revision_same_id_rejected(self):
        self.prepare();v=self.c.observe()
        with self.assertRaisesRegex(Exception,'OPERATION_ID_CONFLICT'):self.d.prepare(b'o'*16,expected_revision=1,expected_observation=v['revision'])
    def test_store_generation_mismatch_blocks_binding(self):
        self.prepare();bad=dataclasses.replace(self.j.current,store_generation=b'q'*16)
        other=self.m.IntentJournal.create(self.root.parent/'other',bad.binding());self.addCleanup(other.close)
        with self.assertRaisesRegex(Exception,'JOURNAL_BINDING'):self.m.DurableApplication(other,self.c)
    def test_generation_change_before_dispatch(self):
        self.simulate();self.prepare();v=self.c.observe();self.gen[0]=10
        with self.assertRaisesRegex(Exception,'STALE_GENERATION'):self.d.execute(self.j.current.digest,expected_observation=v['revision'])
        self.assertEqual(self.j.status()['state'],'PREPARED');self.assertEqual(self.port.calls,0)
    def test_input_digest_change_before_dispatch_rejected(self):
        self.simulate();self.prepare();v=self.c.observe();orig=self.app._pool_digest;self.app._pool_digest=lambda p:b'q'*32
        try:
            with self.assertRaisesRegex(Exception,'INPUTS_CHANGED'):self.d.execute(self.j.current.digest,expected_observation=v['revision'])
        finally:self.app._pool_digest=orig
        self.assertEqual(self.j.status()['state'],'PREPARED');self.assertEqual(self.port.calls,0)
    def test_cancel_before_dispatch_does_not_poison(self):
        self.simulate();self.prepare();event=asyncio.Event();event.set();v=self.execute(cancel=event)
        self.assertEqual(v['operationState'],'CANCELLED');self.assertEqual(self.j.status()['state'],'PREPARED')
    def test_cancel_after_dispatch_does_not_apply_or_replay(self):
        self.simulate();self.prepare();event=asyncio.Event()
        def after(stage):
            if stage=='journal.after_dirsync':event.set()
        self.j.observer=after;v=self.execute(cancel=event)
        self.assertEqual(v['operationState'],'OUTCOME_UNKNOWN');self.assertEqual(self.port.calls,0);self.assertEqual(self.j.status()['state'],'DISPATCHED')
    def test_task_cancel_after_commit_still_inquiry_only(self):
        self.simulate();self.prepare();orig=self.app.apply
        def after(*a,**kw):orig(*a,**kw);raise asyncio.CancelledError
        self.app.apply=after
        with self.assertRaises(asyncio.CancelledError):self.execute()
        self.assertEqual(self.j.status()['state'],'DISPATCHED');self.assertEqual(self.nums()['document_apply_events'],1)
    def test_retire_checks_current_record_not_old_observation(self):
        self.simulate();self.prepare();self.execute();self.app.inquire=lambda *a,**k:None
        with self.assertRaisesRegex(Exception,'RECEIPT_REQUIRED'):self.d.retire(self.j.current.digest)
        self.assertEqual(self.j.status()['state'],'OBSERVED')
    def test_matching_receipt_explicit_retire_preserves_record(self):
        self.simulate();self.prepare();self.execute();dg=self.j.current.digest;v=self.d.retire(dg)
        self.assertEqual(v['state'],'RETIRED');self.assertEqual(self.nums()['document_apply_events'],1)
    def test_inquiry_failure_does_not_unlock(self):
        self.prepare();self.j.dispatch(self.j.current.digest)
        def failure(*a,**k):raise RuntimeError('lost')
        self.app.inquire=failure;v=self.d.inquire(self.j.current.digest);self.assertEqual(v['operationState'],'INQUIRY_FAILED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):self.execute()
    def test_explicit_abandon_before_dispatch(self):
        self.prepare();v=self.d.abandon(self.j.current.digest);self.assertEqual(v['state'],'ABANDONED');self.assertEqual(self.port.calls,0)
    def test_current_authority_checked_for_inquiry(self):
        self.prepare();self.j.dispatch(self.j.current.digest)
        def deny():raise RuntimeError('revoked')
        self.app._auth=deny;v=self.d.inquire(self.j.current.digest);self.assertEqual(v['operationState'],'INQUIRY_FAILED');self.assertEqual(v['state'],'DISPATCHED')
    def test_same_intent_after_retire_never_reexecutes(self):
        self.simulate();self.prepare();self.execute();self.d.retire(self.j.current.digest);calls=self.port.calls
        with self.assertRaises(Exception):self.execute()
        self.assertEqual(self.port.calls,calls)
    def test_absence_cannot_demote_prior_receipt(self):
        self.simulate();self.prepare();self.execute();self.app.inquire=lambda *a,**k:None
        v=self.d.inquire(self.j.current.digest);self.assertEqual(v['operationState'],'INQUIRY_FAILED');self.assertEqual(v['reason'],'RECEIPT_CONFLICT');self.assertIsNotNone(v['receipt'])
    def test_synchronous_timeout_after_commit_remains_unknown(self):
        import time
        from unittest.mock import patch
        self.simulate();self.prepare();original=self.app.apply;clock=time.monotonic();advance=[0]
        def after(*a,**k):
            r=original(*a,**k);advance[0]=100;return r
        self.app.apply=after
        with patch('product.wp09.par_application_intent.coordinator.time.monotonic',lambda:clock+advance[0]):v=self.execute(timeout=1)
        self.assertEqual(v['operationState'],'OUTCOME_UNKNOWN');self.assertEqual(v['reason'],'INTENT_DEADLINE');self.assertEqual(self.nums()['document_apply_events'],1)
    def test_invalid_cancel_argument_does_not_write_dispatch(self):
        self.prepare()
        with self.assertRaisesRegex(Exception,'INVALID_CANCEL'):self.execute(cancel=True)
        self.assertEqual(self.j.status()['state'],'PREPARED')
