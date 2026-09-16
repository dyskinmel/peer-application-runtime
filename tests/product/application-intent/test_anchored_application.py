"""Real persistence/SQLite with explicitly SYNTHETIC core transaction fixtures."""
import importlib,unittest
from unittest.mock import patch
import test_intent_coordinator as fixtures

class AnchoredApplicationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.IntentCoordinatorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;self.a=importlib.import_module('product.wp09.par_application_intent.anchors')
        self.assertTrue(hasattr(f.m,'AnchoredApplication'),'anchored mutation capability missing')
        self.store=self.a.LocalPinStore.create(f.root.parent/'anchor',f.m.DurableApplication.binding(f.c),f.j.pin());self.addCleanup(self.store.close)
        self.reopen()
    def reopen(self):
        f=self.f;f.j.close();f.app=f.make(inbox=f.box,allow_contract_double=False);f.c=f.controller();f.j=f.m.IntentJournal.open_anchored(f.root.parent/'intents',f.m.DurableApplication.binding(f.c),self.store)
        f.addCleanup(f.j.close);f.d=f.m.AnchoredApplication(f.j,f.c)
    def test_unanchored_mutation_capability_refused(self):
        f=self.f;pin=f.j.pin();f.j.close();f.j=f.m.IntentJournal.open(f.root.parent/'intents',f.m.DurableApplication.binding(f.c),expected_pin=pin);f.addCleanup(f.j.close)
        with self.assertRaisesRegex(Exception,'PIN_STORE_REQUIRED'):f.m.AnchoredApplication(f.j,f.c)
    def test_prepare_is_anchored_before_ack(self):
        f=self.f;r=f.prepare();self.assertEqual(r['state'],'PREPARED');self.assertEqual(self.store.load(),f.j.pin());self.assertEqual(f.nums()['document_apply_nonces'],0)
    def test_dispatch_pin_exists_before_nonce(self):
        f=self.f;f.simulate();f.prepare();seen=[]
        def witness(stage):
            if stage=='apply.nonce_after_commit':
                pinned=self.store.load()==f.j.pin()  # Observe before status() can audit/sync.
                seen.append((f.j.status()['state'],pinned))
        f.app.observer=witness;r=f.execute();self.assertEqual(seen,[('DISPATCHED',True)]);self.assertEqual(r['state'],'OBSERVED');self.assertEqual(self.store.load(),f.j.pin())
    def test_dispatch_anchor_failure_never_calls_apply(self):
        f=self.f;f.simulate();f.prepare()
        with patch.object(self.store,'advance',side_effect=OSError('external unavailable')):
            with self.assertRaisesRegex(Exception,'PERSISTENCE_UNKNOWN'):f.execute()
        self.assertEqual(f.port.calls,0);self.assertEqual(f.nums()['document_apply_nonces'],0)
        self.reopen();r=f.d.inquire(f.j.current.digest);self.assertEqual(r['operationState'],'NOT_OBSERVED');self.assertEqual(r['state'],'DISPATCHED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):f.execute()
    def test_anchor_response_lost_after_durable_write_never_calls_apply(self):
        f=self.f;f.simulate();f.prepare();advance=self.store.advance
        def lost(old,new):advance(old,new);raise OSError('lost response')
        with patch.object(self.store,'advance',lost):
            with self.assertRaisesRegex(Exception,'PERSISTENCE_UNKNOWN'):f.execute()
        self.assertEqual(f.port.calls,0);self.reopen();self.assertEqual(f.j.status()['state'],'DISPATCHED')
    def test_commit_response_loss_reconciles_without_core(self):
        f=self.f;f.simulate();f.prepare()
        def lost(stage):
            if stage=='apply.after_commit':raise OSError('response lost')
        f.app.observer=lost;r=f.execute();self.assertEqual(r['operationState'],'OUTCOME_UNKNOWN')
        self.reopen();f.app._core=None;calls=f.port.calls;r=f.d.inquire(f.j.current.digest)
        self.assertEqual(r['state'],'OBSERVED');self.assertEqual(calls,f.port.calls);self.assertEqual(self.store.load(),f.j.pin());self.assertEqual(f.nums()['document_apply_events'],1)
    def test_inquiry_anchor_failure_preserves_saved_record(self):
        f=self.f;f.simulate();f.prepare()
        def lost(stage):
            if stage=='apply.after_commit':raise OSError('lost')
        f.app.observer=lost;f.execute();self.reopen()
        with patch.object(self.store,'advance',side_effect=OSError('pin failed')):
            with self.assertRaises(Exception):f.d.inquire(f.j.current.digest)
        self.reopen();r=f.d.inquire(f.j.current.digest);self.assertEqual(r['state'],'OBSERVED');self.assertEqual(f.nums()['document_apply_events'],1)
    def test_retirement_anchor_failure_does_not_reopen_operation(self):
        f=self.f;f.simulate();f.prepare();f.execute();digest=f.j.current.digest
        with patch.object(self.store,'advance',side_effect=OSError('pin failed')):
            with self.assertRaises(Exception):f.d.retire(digest)
        self.reopen();self.assertEqual(f.j.status()['state'],'RETIRED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):f.execute()
    def test_core_unavailable_stays_prepared(self):
        f=self.f;f.prepare();f.app._core=None;r=f.execute();self.assertEqual(r['reason'],'CORE_UNAVAILABLE');self.assertEqual(f.j.status()['state'],'PREPARED');self.assertEqual(self.store.load(),f.j.pin())
    def test_closed_anchor_blocks_effects(self):
        f=self.f;f.simulate();f.prepare();self.store.close()
        with self.assertRaisesRegex(Exception,'PIN_STORE_CLOSED'):f.execute()
        self.assertEqual(f.port.calls,0)
    def test_anchor_dropped_after_binding_refuses_effect(self):
        f=self.f;f.prepare();f.j._anchor=None
        with self.assertRaisesRegex(Exception,'PIN_STORE_REQUIRED'):f.execute()
    def test_idempotent_inquiry_does_not_write_pin(self):
        f=self.f;f.simulate();f.prepare();f.execute()
        with patch.object(self.store,'advance',side_effect=AssertionError('duplicate write')):
            self.assertEqual(f.d.inquire(f.j.current.digest)['state'],'OBSERVED')
