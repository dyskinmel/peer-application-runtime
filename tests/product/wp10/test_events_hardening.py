"""Regression probes for durable nonce/ack evidence, private paths and scope."""
import os,sqlite3,shutil
from test_events import EventTest,h

class HardeningTests(EventTest):
    def test_removed_unused_nonce_is_detected(self):
        self.create();flag=[False]
        self.journal.observer=lambda s:flag.__setitem__(0,True) if s=='event.after_encrypt' else None
        self.emit(cancelled=lambda:flag[0]);self.journal._connection.execute('DELETE FROM nonces')
        self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_nonce_operation_tamper_detected(self):
        self.create();self.emit();self.journal._connection.execute('UPDATE nonces SET operation=?',(b'z'*16,));self.rejects('JOURNAL_CORRUPT',lambda:self.journal.inspect())
    def test_replaced_database_path(self):
        self.create();self.emit();p=self.path/'events.sqlite3';p.rename(p.with_suffix('.old'));shutil.copy2(p.with_suffix('.old'),p)
        self.rejects('PATH_CHANGED',lambda:self.journal.inspect())
    def test_directory_permissions_checked_each_call(self):
        self.create();os.chmod(self.path,0o755);self.rejects('UNSAFE_PATH',lambda:self.journal.inspect());os.chmod(self.path,0o700)
    def test_event_payload_nested_objects_refused(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'p'*16,{'body':{'x':1},'count':1}))
    def test_getitem_side_effect_subclass_refused(self):
        self.create();calls=[]
        class Evil(dict):
            def __getitem__(self,k):calls.append(k);return super().__getitem__(k)
        self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'p'*16,Evil(body='x',count=1)));self.assertEqual(calls,[])
    def test_after_encrypt_failure_redacted(self):
        self.create()
        def fail(stage):
            if stage=='event.after_encrypt':raise OSError('private payload')
        self.journal.observer=fail;self.rejects('STORAGE_ERROR',lambda:self.emit());self.journal.observer=None
        self.assertEqual(self.journal.inspect()['events'],0);self.assertEqual(self.journal.inspect()['nonces'],1)
    def test_ack_write_failure_reopen_redelivers(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);b=s.poll()
        def fail(stage):
            if stage=='ack.after_update':raise OSError('no space')
        self.journal.observer=fail;self.rejects('STORAGE_ERROR',lambda:s.ack(b.token));self.reopen();self.assertEqual(self.journal.subscribe(b'c'*16).poll().events,b.events)
    def test_ack_after_commit_unknown_is_stored(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);b=s.poll()
        def fail(stage):
            if stage=='ack.after_commit':raise OSError('lost reply')
        self.journal.observer=fail;self.rejects('EVENT_OUTCOME_UNKNOWN',lambda:s.ack(b.token));self.reopen();self.assertEqual(self.journal.subscribe(b'c'*16).poll().events,())
    def test_consumer_capacity(self):
        self.create(max_consumers=1);self.journal.subscribe(b'a'*16);self.rejects('RESOURCE_LIMIT',lambda:self.journal.subscribe(b'b'*16))
    def test_byte_capacity_no_nonce(self):
        self.create(max_bytes=1024);self.rejects('RESOURCE_LIMIT',lambda:self.journal.publish(b'o'*16,{'body':'x'*1024,'count':1}));self.assertEqual(self.journal.inspect()['nonces'],0)
    def test_uint64_max(self):
        self.create();self.journal.publish(b'o'*16,{'body':'x','count':2**64-1});s=self.journal.subscribe(b'c'*16);self.assertEqual(self.events.decode_payload(s.poll().events[0].payload)['count'],2**64-1)
    def test_schema_types_int_bool_bytes(self):
        self.create(schema={'n':'int64','b':'bool','raw':'bytes'});self.journal.publish(b'o'*16,{'n':-2**63,'b':False,'raw':b'bytes'});self.assertEqual(self.events.decode_payload(self.journal.subscribe(b'c'*16).poll().events[0].payload),{'n':-2**63,'b':False,'raw':b'bytes'})
    def test_presence_payload_schema_not_event_injection(self):
        self.create();self.rejects('SCHEMA_INVALID',lambda:self.journal.publish(b'o'*16,{'kind':'presence'}))
    def test_real_database_lock_refused(self):
        self.create();other=sqlite3.connect(self.path/'events.sqlite3',isolation_level=None);other.execute('BEGIN IMMEDIATE')
        try:self.rejects('STORAGE_BUSY',lambda:self.emit())
        finally:other.execute('ROLLBACK');other.close()
        self.assertEqual(self.journal.inspect()['events'],0)
    def test_real_sqlite_full(self):
        self.create(max_bytes=1024*1024)
        c=self.journal._connection;pages=c.execute('PRAGMA page_count').fetchone()[0];c.execute(f'PRAGMA max_page_count={pages}')
        self.rejects('STORAGE_FULL',lambda:self.journal.publish(b'o'*16,{'body':'x'*16000,'count':1}))
        self.assertEqual(self.journal.inspect()['events'],0)
    def test_guard_change_after_poll_has_no_ack(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);b=s.poll();self.same_epoch();self.rejects('AUTHORITY_CHANGED',lambda:s.ack(b.token));self.assertEqual(s.position,0)
    def test_poll_result_immutable(self):
        from dataclasses import FrozenInstanceError
        self.create();self.emit();b=self.journal.subscribe(b'c'*16).poll()
        with self.assertRaises(FrozenInstanceError):b.events[0].payload=b'other'
    def test_reentrant_publish_refused(self):
        self.create();codes=[]
        def observer(stage):
            if stage=='event.after_encrypt':
                try:self.journal.publish(b'r'*16,{'body':'x','count':1})
                except Exception as e:codes.append(e.code)
        self.journal.observer=observer;self.emit();self.assertEqual(codes,['REENTRANT_OPERATION'])
    def test_acknowledged_cursor_rollback_detected_immediately(self):
        self.create();self.emit();s=self.journal.subscribe(b'c'*16);old=tuple(self.journal._connection.execute('SELECT * FROM consumers').fetchone());s.ack(s.poll().token)
        self.journal._connection.execute('INSERT OR REPLACE INTO consumers VALUES(?,?,?,?,?)',old)
        self.rejects('JOURNAL_CORRUPT',lambda:s.cursor())
    def test_commit_then_deleted_event_is_unknown(self):
        self.create()
        def mutate(stage):
            if stage=='event.after_commit':self.journal._connection.execute('DELETE FROM events')
        self.journal.observer=mutate
        self.rejects('EVENT_OUTCOME_UNKNOWN',lambda:self.emit())
