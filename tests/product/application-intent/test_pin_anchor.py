"""External pin adapter tests. POSIX local trust, not hardware rollback resistance."""
import dataclasses,importlib,importlib.util,os,threading,unittest
from pathlib import Path
from unittest.mock import patch
from intent_support import JournalTest
from product.wp09.par_secure_fetch.persistence import FetchError

class PinAnchorTests(JournalTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_application_intent.anchors'), 'pin adapter is not implemented')
        self.a=importlib.import_module('product.wp09.par_application_intent.anchors')
        self.j=self.create();self.initial=self.j.pin()
        self.pinroot=self.parent/'external-anchor'
        self.store=self.a.LocalPinStore.create(self.pinroot,self.intent.binding(),self.initial);self.addCleanup(self.store.close)
    def reopen_store(self):
        self.store.close();self.store=self.a.LocalPinStore.open(self.pinroot,self.intent.binding());self.addCleanup(self.store.close);return self.store
    def anchored(self):
        self.j.close();self.j=self.m.IntentJournal.open_anchored(self.root,self.intent.binding(),self.store);self.addCleanup(self.j.close);return self.j
    def test_initial_pin_survives_reopen(self):self.assertEqual(self.reopen_store().load(),self.initial)
    def test_create_is_never_upsert(self):
        with self.assertRaises(FetchError):self.a.LocalPinStore.create(self.pinroot,self.intent.binding(),self.initial)
    def test_wrong_binding_rejected(self):
        self.store.close()
        with self.assertRaisesRegex(FetchError,'PIN_STORE_BINDING'):self.a.LocalPinStore.open(self.pinroot,self.new_intent(store_generation=b'x'*16).binding())
    def test_missing_store_not_enrolled_on_open(self):
        with self.assertRaises(Exception):self.a.LocalPinStore.open(self.parent/'absent',self.intent.binding())
        self.assertFalse((self.parent/'absent').exists())
    def test_compare_swap_advances_real_bytes(self):
        self.j.prepare(self.intent);pin=self.j.pin();self.store.advance(self.initial,pin)
        self.assertEqual(self.reopen_store().load(),pin)
    def test_old_expected_pin_rejected(self):
        self.j.prepare(self.intent);pin=self.j.pin();self.store.advance(self.initial,pin)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_CONFLICT'):self.store.advance(self.initial,pin)
    def test_pin_regression_rejected(self):
        self.j.prepare(self.intent);pin=self.j.pin();self.store.advance(self.initial,pin)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_REGRESSION'):self.store.advance(pin,self.initial)
    def test_same_sequence_different_hash_rejected(self):
        self.j.prepare(self.intent);pin=self.j.pin();self.store.advance(self.initial,pin)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_CONFLICT'):self.store.advance(pin,dataclasses.replace(pin,event_digest='f'*64))
    def test_different_metadata_rejected(self):
        other=self.m.JournalPin('d'*64,0,'d'*64)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_BINDING'):self.store.advance(self.initial,other)
    def test_idempotent_pin_has_no_write(self):
        before={p.name:p.read_bytes()for p in self.pinroot.iterdir()}
        with patch.object(self.a,'sync_dir',side_effect=AssertionError('unexpected write')):self.store.advance(self.initial,self.initial)
        self.assertEqual(before,{p.name:p.read_bytes()for p in self.pinroot.iterdir()})
    def test_broad_permissions_rejected(self):
        self.store.close();(self.pinroot/'pin.json').chmod(0o644)
        with self.assertRaises(Exception):self.reopen_store()
    def test_symlink_rejected(self):
        self.store.close();p=self.pinroot/'pin.json';raw=p.read_bytes();other=self.parent/'other';other.write_bytes(raw);other.chmod(0o600);p.unlink();p.symlink_to(other)
        with self.assertRaises(Exception):self.reopen_store()
    def test_partial_write_is_not_empty_pin(self):
        self.store.close();p=self.pinroot/'pending.json';p.write_bytes(b'{');p.chmod(0o600)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_UNCERTAIN'):self.reopen_store()
    def test_corrupt_file_rejected(self):
        self.store.close();(self.pinroot/'pin.json').write_bytes(b'{')
        with self.assertRaisesRegex(FetchError,'PIN_STORE_CORRUPT'):self.reopen_store()
    def test_second_owner_denied(self):
        with self.assertRaisesRegex(FetchError,'PIN_STORE_LOCKED'):self.a.LocalPinStore.open(self.pinroot,self.intent.binding())
    def test_foreign_thread_denied(self):
        errors=[]
        def other():
            try:self.store.load()
            except FetchError as e:errors.append(e.code)
        t=threading.Thread(target=other);t.start();t.join();self.assertEqual(errors,['WRONG_OWNER'])
    def test_observed_pin_rollback_rejected(self):
        raw=(self.pinroot/'pin.json').read_bytes();self.j.prepare(self.intent);pin=self.j.pin();self.store.advance(self.initial,pin)
        (self.pinroot/'pin.json').write_bytes(raw)
        with self.assertRaisesRegex(FetchError,'PIN_STORE_CONFLICT'):self.store.load()
    def test_anchored_prepare_updates_external_pin(self):
        j=self.anchored();j.prepare(self.intent);self.assertEqual(self.store.load(),j.pin());self.assertTrue(j.anchored)
    def test_missing_adapter_refuses_anchored_open(self):
        self.j.close()
        with self.assertRaisesRegex(FetchError,'PIN_STORE_REQUIRED'):self.m.IntentJournal.open_anchored(self.root,self.intent.binding(),None)
    def test_pin_failure_poisoned_before_dispatch(self):
        j=self.anchored()
        with patch.object(self.store,'advance',side_effect=OSError('pin unavailable')):
            with self.assertRaisesRegex(FetchError,'PERSISTENCE_UNKNOWN'):j.prepare(self.intent)
        with self.assertRaisesRegex(FetchError,'JOURNAL_POISONED'):j.dispatch(self.intent.digest)
        self.assertEqual(self.store.load(),self.initial)
    def test_reopen_resyncs_valid_journal_ahead_of_anchor(self):
        j=self.anchored()
        with patch.object(self.store,'advance',side_effect=OSError('pin unavailable')):
            with self.assertRaises(FetchError):j.prepare(self.intent)
        j.close();j=self.anchored();self.assertEqual(j.status()['state'],'PREPARED');self.assertEqual(self.store.load(),j.pin())
    def test_anchor_ahead_of_truncated_journal_rejected(self):
        j=self.anchored();j.prepare(self.intent);j.close();next((self.root/'events').iterdir()).unlink()
        with self.assertRaisesRegex(FetchError,'JOURNAL_PIN'):self.anchored()
    def test_anchor_disk_sync_failure_is_unknown(self):
        self.j.prepare(self.intent)
        with patch.object(self.a,'sync_dir',side_effect=OSError('sync failure')):
            with self.assertRaisesRegex(FetchError,'PIN_STORE_UNCERTAIN'):self.store.advance(self.initial,self.j.pin())
        with self.assertRaisesRegex(FetchError,'PIN_STORE_POISONED'):self.store.load()
    def test_anchor_inside_journal_is_refused(self):
        # Path alias is denied before changing the immutable journal layout.
        self.store.close()
        self.assertFalse((self.root/'anchor').exists())
        class Embedded(self.a.PinStore):
            binding=self.intent.binding();root=self.root/'anchor'
            def load(s):return self.initial
            def advance(s,old,new):pass
        self.j.close()
        with self.assertRaisesRegex(FetchError,'PIN_STORE_LOCATION'):self.m.IntentJournal.open_anchored(self.root,self.intent.binding(),Embedded())
    def test_lease_permissions_changed_after_open_are_rejected(self):
        (self.pinroot/'lease').chmod(0o666)
        with self.assertRaisesRegex(FetchError,'UNSAFE_PATH'):self.store.load()
    def test_provider_ack_without_durable_readback_is_rejected(self):
        class Lying(self.a.PinStore):
            binding=self.intent.binding()
            def load(s):return self.initial
            def advance(s,old,new):return None
        self.j.close();j=self.m.IntentJournal.open_anchored(self.root,self.intent.binding(),Lying());self.addCleanup(j.close)
        with self.assertRaisesRegex(FetchError,'PERSISTENCE_UNKNOWN'):j.prepare(self.intent)
        self.assertTrue(j._poisoned)
