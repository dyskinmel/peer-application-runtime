import dataclasses,hashlib,json,os,stat
from unittest.mock import patch
from intent_support import JournalTest

class IntentEncodingTests(JournalTest):
    def test_roundtrip_and_digest(self):
        raw=self.intent.to_bytes();self.assertEqual(self.m.ApplicationIntent.from_bytes(raw),self.intent)
        self.assertEqual(self.intent.digest,hashlib.sha256(raw).hexdigest())
    def test_intent_is_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):self.intent.expected_revision=2
    def test_target_order_is_canonical_and_owned(self):
        xs=[b'z'*32,b'a'*32];i=self.new_intent(targets=xs);xs.clear()
        self.assertEqual(i.targets,(b'a'*32,b'z'*32))
    def test_duplicate_targets_rejected(self):
        with self.assertRaises(Exception):self.new_intent(targets=[b't'*32,b't'*32])
    def test_boolean_and_invalid_revision_rejected(self):
        for v in (True,-1,64,'0'):
            with self.subTest(v=v),self.assertRaises(Exception):self.new_intent(expected_revision=v)
    def test_operation_and_generation_lengths_rejected(self):
        for k,v in [('operation_id',b'o'),('store_generation',b'g'),('inbox_generation','X'*32),('connection_generation',True)]:
            with self.subTest(k=k),self.assertRaises(Exception):self.new_intent(**{k:v})
    def test_each_meaningful_input_changes_digest(self):
        for kw in [dict(targets=[b'q'*32]),dict(expected_revision=1),dict(authority_digest=b'a'*32),dict(input_digest=b'p'*32),dict(connection_generation=10)]:
            self.assertNotEqual(self.new_intent(**kw).digest,self.intent.digest)
    def test_decoder_refuses_trailing_bytes(self):
        with self.assertRaises(Exception):self.m.ApplicationIntent.from_bytes(self.intent.to_bytes()+b'x')

class IntentJournalTests(JournalTest):
    def test_prepare_reopens_as_prepared_without_dispatch(self):
        j=self.create();j.prepare(self.intent);pin=j.pin();j=self.reopen(j,pin)
        self.assertEqual(j.status()['state'],'PREPARED');self.assertEqual(j.current,self.intent)
    def test_same_id_same_intent_is_noop(self):
        j=self.create();j.prepare(self.intent);pin=j.pin();j.prepare(self.intent);self.assertEqual(j.pin(),pin)
    def test_same_id_changed_intent_rejected(self):
        j=self.create();j.prepare(self.intent)
        with self.assertRaisesRegex(Exception,'OPERATION_ID_CONFLICT'):j.prepare(self.new_intent(expected_revision=1))
    def test_other_id_cannot_replace_active_intent(self):
        j=self.create();j.prepare(self.intent)
        with self.assertRaisesRegex(Exception,'ACTIVE_INTENT'):j.prepare(self.new_intent(operation_id=b'p'*16))
    def test_dispatch_requires_original_digest(self):
        j=self.create();j.prepare(self.intent)
        with self.assertRaisesRegex(Exception,'INTENT_PIN'):j.dispatch('0'*64)
    def test_dispatched_reopen_never_replays(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest);j=self.reopen(j)
        self.assertEqual(j.status()['state'],'DISPATCHED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):j.dispatch(self.intent.digest)
    def test_prepared_only_explicit_abandon(self):
        j=self.create();j.prepare(self.intent);j.abandon(self.intent.digest)
        self.assertEqual(j.status()['state'],'ABANDONED')
        with self.assertRaisesRegex(Exception,'OPERATION_RETIRED'):j.prepare(self.intent)
    def test_dispatched_cannot_be_abandoned(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest)
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):j.abandon(self.intent.digest)
    def test_retire_requires_observed_receipt(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest)
        with self.assertRaisesRegex(Exception,'RECEIPT_REQUIRED'):j.retire(self.intent.digest)
    def test_observe_and_retire_preserve_tombstone(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest);j.observe(self.intent.digest,self.receipt());j.retire(self.intent.digest)
        j=self.reopen(j);self.assertEqual(j.status()['state'],'RETIRED')
        with self.assertRaisesRegex(Exception,'OPERATION_RETIRED'):j.prepare(self.intent)
        j.prepare(self.new_intent(operation_id=b'p'*16,expected_revision=1));self.assertEqual(j.status()['state'],'PREPARED')
    def test_receipt_wrong_operation_revision_targets_rejected(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest)
        for kw in [dict(operationId='a'*32),dict(revision=2),dict(inputIds=['f'*64]),dict(applied=True),dict(replicated=True)]:
            with self.subTest(kw=kw),self.assertRaises(Exception):j.observe(self.intent.digest,self.receipt(**kw))
        self.assertEqual(j.status()['state'],'DISPATCHED')
    def test_observed_receipt_conflict_rejected(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest);j.observe(self.intent.digest,self.receipt())
        with self.assertRaisesRegex(Exception,'RECEIPT_CONFLICT'):j.observe(self.intent.digest,self.receipt(eventDigest='3'*64))
    def test_pin_prevents_known_tail_deletion(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest);pin=j.pin();j.close()
        (self.root/'events'/'00000002.json').unlink()
        with self.assertRaisesRegex(Exception,'JOURNAL_PIN'):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
    def test_older_pin_accepts_durable_descendant(self):
        j=self.create();j.prepare(self.intent);pin=j.pin();j.dispatch(self.intent.digest);j=self.reopen(j,pin)
        self.assertEqual(j.status()['state'],'DISPATCHED')
    def test_wrong_root_pin_rejected(self):
        j=self.create();pin=j.pin();j.close();bad=dataclasses.replace(pin,metadata_digest='0'*64,event_digest='0'*64)
        with self.assertRaisesRegex(Exception,'JOURNAL_PIN'):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=bad)
    def test_partial_event_blocks_not_empty(self):
        j=self.create();pin=j.pin();j.close();p=self.root/'events'/'00000001.json';p.write_bytes(b'{');p.chmod(0o600)
        with self.assertRaises(Exception):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
    def test_same_process_second_writer_rejected(self):
        j=self.create()
        with self.assertRaisesRegex(Exception,'JOURNAL_LOCKED'):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=j.pin())
    def test_private_permissions(self):
        j=self.create();j.prepare(self.intent)
        for p in [self.root,self.root/'events']:self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o700)
        for p in [self.root/'metadata.json',self.root/'lease',self.root/'events'/'00000001.json']:self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
    def test_symlink_event_rejected(self):
        j=self.create();j.prepare(self.intent);pin=j.pin();j.close();p=self.root/'events'/'00000001.json';other=self.parent/'copy';p.rename(other);p.symlink_to(other)
        with self.assertRaises(Exception):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
    def test_hardlink_event_rejected(self):
        j=self.create();j.prepare(self.intent);pin=j.pin();j.close();os.link(self.root/'events'/'00000001.json',self.parent/'linked')
        with self.assertRaises(Exception):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
    def test_directory_mode_rejected(self):
        j=self.create();pin=j.pin();j.close();(self.root/'events').chmod(0o755)
        with self.assertRaises(Exception):self.m.IntentJournal.open(self.root,self.intent.binding(),expected_pin=pin)
    def test_prepare_write_failure_poisoned_then_reopen(self):
        j=self.create();pin=j.pin()
        def fault(stage):
            if stage=='journal.after_dirsync':raise OSError('injected')
        j.observer=fault
        with self.assertRaisesRegex(Exception,'PERSISTENCE_UNKNOWN'):j.prepare(self.intent)
        with self.assertRaisesRegex(Exception,'JOURNAL_POISONED'):j.prepare(self.new_intent(operation_id=b'p'*16))
        j=self.reopen(j,pin);self.assertEqual(j.status()['state'],'PREPARED')
    def test_event_tamper_detected_before_dispatch(self):
        j=self.create();j.prepare(self.intent);p=self.root/'events'/'00000001.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(Exception):j.dispatch(self.intent.digest)
    def test_wrong_binding_rejected(self):
        j=self.create();pin=j.pin();j.close()
        with self.assertRaisesRegex(Exception,'JOURNAL_BINDING'):self.m.IntentJournal.open(self.root,self.new_intent(store_generation=b'x'*16).binding(),expected_pin=pin)
    def test_status_is_owned(self):
        j=self.create();j.prepare(self.intent);s=j.status();s['state']='RETIRED';self.assertEqual(j.status()['state'],'PREPARED')
    def test_identical_observation_does_not_consume_event_budget(self):
        j=self.create();j.prepare(self.intent);j.dispatch(self.intent.digest);j.observe(self.intent.digest,self.receipt());pin=j.pin()
        j.observe(self.intent.digest,self.receipt());self.assertEqual(pin,j.pin())
    def test_deleted_known_event_poisoned_in_live_handle(self):
        j=self.create();j.prepare(self.intent);(self.root/'events'/'00000001.json').unlink()
        with self.assertRaisesRegex(Exception,'JOURNAL_PIN'):j.status()
        with self.assertRaisesRegex(Exception,'JOURNAL_POISONED'):j.dispatch(self.intent.digest)
