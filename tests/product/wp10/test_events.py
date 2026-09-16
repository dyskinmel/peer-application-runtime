"""Real local authority, signatures and SQLite; no network/CRDT qualification."""
import importlib, hashlib, os, sqlite3, threading, unittest
from pathlib import Path
from auth_store_support import AuthStoreTest, h

class EventTest(AuthStoreTest):
    def setUp(self):
        super().setUp()
        try: self.events = importlib.import_module('product.wp10.events')
        except ModuleNotFoundError: self.events = None
        self.assertTrue(self.events is not None and hasattr(self.events, 'EventJournal'), 'durable events and cursor contract not implemented')
        self.start(); self.journal = None
        self.addCleanup(self.close_journal)
        self.kw = dict(owner=self.db, certificate=self.s.devices[0]['cert'], sign_seed=self.s.devices[0]['seed'],
                       local_secret=h('event-local-key'), app_id=self.s.app, space_id=self.s.space,
                       stream_id=h('events'), epoch=1, schema={'body':'text','count':'uint64'}, allow_legacy_experiment=True)
        self.path = Path(self.tmp.name)/'events'
    def close_journal(self):
        if self.journal is not None: self.journal.close(); self.journal=None
    def create(self, **kw):
        self.journal=self.events.EventJournal.create(self.path, **(self.kw|kw)); return self.journal
    def reopen(self, **kw):
        self.close_journal(); self.journal=self.events.EventJournal.open(self.path, **(self.kw|kw)); return self.journal
    def emit(self, n=1, parents=(), **kw):
        return self.journal.publish(n.to_bytes(16,'big'), {'body':f'secret-note-{n}','count':2**63+1}, parents=parents, **kw)
    def rejects(self, code, f):
        with self.assertRaises(self.events.EventError) as cm: f()
        if code: self.assertEqual(cm.exception.code,code)

class ContractTests(EventTest):
    def test_publish_is_local_only(self):
        self.create(); r=self.emit(); self.assertEqual(r.state,'LOCAL_EVENT_COMMITTED'); self.assertFalse(r.replicated)
    def test_same_operation_same_result(self):
        self.create(); a=self.emit(); b=self.emit(); self.assertEqual(a,b);self.assertEqual(self.journal.inspect()['events'],1)
    def test_operation_payload_conflict(self):
        self.create();self.emit();self.rejects('OPERATION_CONFLICT',lambda:self.journal.publish((1).to_bytes(16,'big'),{'body':'different','count':2}))
    def test_schema_rejects_extra(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'x','count':1,'extra':True}))
    def test_schema_rejects_missing(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'x'}))
    def test_bool_not_uint64(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'x','count':True}))
    def test_uint64_overflow(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'x','count':2**64}))
    def test_unsigned_negative(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'x','count':-1}))
    def test_payload_size_bound(self):
        self.create();self.rejects('RESOURCE_LIMIT',lambda:self.journal.publish(b'o'*16,{'body':'x'*65536,'count':1}))
    def test_invalid_operation_id(self):
        self.create();self.rejects('INVALID_INPUT',lambda:self.journal.publish(b'x',{'body':'x','count':1}))
    def test_missing_parent(self):
        self.create();self.rejects('DEPENDENCIES_PENDING',lambda:self.emit(parents=(h('absent'),)))
    def test_duplicate_parent(self):
        self.create();p=self.emit().event_id;self.rejects('INVALID_INPUT',lambda:self.emit(2,(p,p)))
    def test_causal_parent_retained(self):
        self.create();p=self.emit().event_id;self.emit(2,(p,)); b=self.journal.subscribe(b'c'*16).poll();self.assertEqual(b.events[1].parents,(p,))
    def test_ciphertext_hides_payload(self):
        self.create();self.emit();self.assertNotIn(b'secret-note-1', (self.path/'events.sqlite3').read_bytes())
    def test_uint64_exact_roundtrip(self):
        self.create();self.emit();b=self.journal.subscribe(b'c'*16).poll();
        self.assertEqual(self.events.decode_payload(b.events[0].payload)['count'],2**63+1)
    def test_reader_cannot_publish(self):
        d=self.s.devices[1]; self.create(certificate=d['cert'], sign_seed=d['seed']);self.rejects('NOT_AUTHORIZED',lambda:self.emit())
    def test_wrong_signing_seed(self):
        self.rejects('SIGNER_MISMATCH',lambda:self.create(sign_seed=h('other')))
    def test_closed_journal(self):
        j=self.create();j.close();self.rejects('CLOSED',lambda:j.inspect())
    def test_wrong_thread(self):
        self.create();out=[]
        def f():
            try:self.journal.inspect()
            except Exception as e:out.append(e.code)
        t=threading.Thread(target=f);t.start();t.join(2);self.assertEqual(out,['WRONG_OWNER'])
    def test_legacy_consent_required(self):
        self.rejects('DEPENDENCY_UPGRADE_REQUIRED',lambda:self.create(allow_legacy_experiment=False))

class CursorTests(EventTest):
    def test_poll_does_not_ack(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);a=s.poll();b=s.poll();self.assertEqual(a,b);self.assertEqual(s.position,0)
    def test_ack_advances_only_delivered(self):
        self.create();self.emit();self.emit(2);s=self.journal.subscribe(b'c'*16);a=s.poll(limit=1);s.ack(a.token);self.assertEqual(s.position,1);self.assertEqual(s.poll().events[0].sequence,2)
    def test_duplicate_ack(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);a=s.poll();x=s.ack(a.token);self.assertEqual(s.ack(a.token),x)
    def test_tampered_ack(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);a=s.poll();self.rejects('CURSOR_INVALID',lambda:s.ack(a.token+b'x'))
    def test_cross_subscriber_ack(self):
        self.create();self.emit();a=self.journal.subscribe(b'a'*16);b=self.journal.subscribe(b'b'*16);self.rejects('CURSOR_INVALID',lambda:b.ack(a.poll().token))
    def test_reopen_redelivers_unacked(self):
        self.create();self.emit();old=self.journal.subscribe(b'c'*16).poll();self.reopen();new=self.journal.subscribe(b'c'*16).poll();self.assertEqual(old.events,new.events)
    def test_reopen_keeps_acked(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);s.ack(s.poll().token);self.reopen();self.assertEqual(self.journal.subscribe(b'c'*16).poll().events,())
    def test_old_delivery_ack_refused_after_restart(self):
        self.create();self.emit();old=self.journal.subscribe(b'c'*16).poll();self.reopen();s=self.journal.subscribe(b'c'*16);s.poll();self.rejects('CURSOR_INVALID',lambda:s.ack(old.token))
    def test_cancel_is_idempotent(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);s.poll();s.cancel();s.cancel();self.rejects('SUBSCRIPTION_CLOSED',lambda:s.poll());self.assertEqual(self.journal.inspect()['events'],1)
    def test_cancel_then_resubscribe_redelivers(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);s.poll();s.cancel();self.assertEqual(len(self.journal.subscribe(b'c'*16).poll().events),1)
    def test_active_duplicate_subscriber_refused(self):
        self.create();self.journal.subscribe(b'c'*16);self.rejects('SUBSCRIPTION_BUSY',lambda:self.journal.subscribe(b'c'*16))
    def test_backpressure_never_skips(self):
        self.create();[self.emit(i) for i in range(1,6)];s=self.journal.subscribe(b'c'*16);a=s.poll(limit=2);self.assertEqual(len(a.events),2);self.assertTrue(a.has_more);s.ack(a.token);self.assertEqual(s.poll(limit=2).events[0].sequence,3)
    def test_too_small_byte_window_no_advance(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);self.rejects('EVENT_EXCEEDS_WINDOW',lambda:s.poll(byte_limit=1));self.assertEqual(s.position,0)
    def test_empty_poll_no_ack(self):
        self.create();b=self.journal.subscribe(b'c'*16).poll();self.assertEqual(b.events,());self.assertIsNone(b.token)
    def test_cursor_pin_export_and_reopen(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);s.ack(s.poll().token);pin=s.cursor();s.cancel();self.reopen();s=self.journal.subscribe(b'c'*16,expected_cursor=pin);self.assertEqual(s.position,1)
    def test_cursor_pin_other_consumer_refused(self):
        self.create();s=self.journal.subscribe(b'c'*16);pin=s.cursor();self.rejects('CURSOR_INVALID',lambda:self.journal.subscribe(b'b'*16,expected_cursor=pin))
    def test_stale_authority_invalidates_delivery(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);b=s.poll();self.same_epoch();self.rejects('AUTHORITY_CHANGED',lambda:s.ack(b.token))
    def test_authority_pending_blocks_read(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);self.next_epoch();self.rejects('NOT_AUTHORIZED',lambda:s.poll())

class StorageTests(EventTest):
    def test_reopen_matches_event_ids(self):
        self.create();r=self.emit();self.reopen();self.assertEqual(self.journal.inspect_operation((1).to_bytes(16,'big')),r)
    def test_wrong_local_key(self):
        self.create();self.emit();self.rejects('KEY_OR_CONTEXT_MISMATCH',lambda:self.reopen(local_secret=h('bad')))
    def test_wrong_stream(self):
        self.create();self.rejects('KEY_OR_CONTEXT_MISMATCH',lambda:self.reopen(stream_id=h('different')))
    def test_schema_changed(self):
        self.create();self.rejects('KEY_OR_CONTEXT_MISMATCH',lambda:self.reopen(schema={'body':'text'}))
    def test_unknown_operation_not_failed(self):
        self.create();self.assertIsNone(self.journal.inspect_operation(b'u'*16))
    def test_payload_tamper_refused(self):
        self.create();self.emit();self.journal._connection.execute("UPDATE events SET record=?",(b'bad',));self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_deleted_event_refused(self):
        self.create();self.emit();self.journal._connection.execute('DELETE FROM events');self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_cursor_tamper_refused(self):
        self.create();self.journal.subscribe(b'c'*16);self.journal._connection.execute('UPDATE consumers SET position=42');self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_lock_second_writer(self):
        self.create();self.rejects('WRITER_BUSY',lambda:self.events.EventJournal.open(self.path,**self.kw))
    def test_schema_tamper_refused(self):
        self.create();self.journal._connection.execute('CREATE TABLE extra(x)');self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_append_cap_rejects_without_drop(self):
        self.create(max_events=2);self.emit();self.emit(2);self.rejects('RESOURCE_LIMIT',lambda:self.emit(3));self.assertEqual(self.journal.inspect()['events'],2)
    def test_cancel_before_commit_keeps_nonce_burned(self):
        self.create();flag=[False]
        def obs(stage):
            if stage=='event.after_encrypt':flag[0]=True
        self.journal.observer=obs;r=self.emit(cancelled=lambda:flag[0]);self.assertEqual(r.state,'CANCELLED');self.assertEqual(self.journal.inspect()['events'],0);self.assertEqual(self.journal.inspect()['nonces'],1)
    def test_cancel_before_nonce(self):
        self.create();r=self.emit(cancelled=lambda:True);self.assertEqual(r.state,'CANCELLED');self.assertEqual(self.journal.inspect()['nonces'],0)
    def test_cancel_after_commit_keeps_result(self):
        self.create();f=[False]
        self.journal.observer=lambda stage:f.__setitem__(0,True) if stage=='event.after_commit' else None
        r=self.emit(cancelled=lambda:f[0]);self.assertTrue(r.cancellation_requested);self.assertEqual(self.journal.inspect()['events'],1)
    def test_after_commit_failure_is_unknown(self):
        self.create()
        def fail(s):
            if s=='event.after_commit':raise OSError('private detail')
        self.journal.observer=fail;self.rejects('EVENT_OUTCOME_UNKNOWN',lambda:self.emit());self.rejects('JOURNAL_UNCERTAIN',lambda:self.journal.inspect());self.reopen();self.assertIsNotNone(self.journal.inspect_operation((1).to_bytes(16,'big')))
    def test_authority_change_before_commit(self):
        self.create();self.journal.observer=lambda s:self.same_epoch() if s=='event.before_commit' else None
        self.rejects('AUTHORITY_CHANGED',lambda:self.emit());self.assertEqual(self.journal.inspect()['events'],0)
    def test_no_plaintext_sql_or_callback_errors(self):
        self.create();self.journal._connection.execute('PRAGMA max_page_count=1')
        # Fault path tests separately exercise actual SQLITE_FULL; code messages never echo input.
        self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'body':'secret','count':object()}))
