"""Real SQLite plus native AEAD. Disposable old-library experiment only."""
import os,signal,subprocess,sys,tempfile
from pathlib import Path
from crypto_support import CryptoTest,ROOT
from test_crypto_objects import header,PAYLOAD,EPOCH,SIGN
from par_store.store import Store
from par_store.errors import StoreError
from par_wire.codec import decode,encode
LOCAL=b'L'*32;OP=b'1'*16;CACHE=b'private materialized snapshot test fixture'
class StoreCryptoTests(CryptoTest):
    def setUp(self):
        super().setUp();self.m=self.require('store_writer');self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'store';self.s=Store.create(self.path,allow_unpatched_sqlite=True);self.addCleanup(self.s.close)
        self.h=header(self.p);self.s.configure_space(self.h[1],self.h[0],1,self.h[13]);self.w=self.writer()
    def writer(self,**kw):return self.m.CryptoStoreWriter(self.p,self.s,EPOCH,SIGN,LOCAL,**kw)
    def commit(self,op=OP,h=None,payload=PAYLOAD,cache=CACHE):return self.w.commit(op,self.h if h is None else h,payload,cache)
    def count(self,table):return self.s.connection.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def store_reject(self,code,fn):
        with self.assertRaises(StoreError) as cm:fn()
        self.assertEqual(cm.exception.code,code)
    def test_atomic_commit_encrypted_and_verified(self):
        r=self.commit();self.assertEqual(self.count('envelopes'),1);self.assertEqual(self.count('issued_nonces'),3)
        self.assertEqual(self.w.read_committed(OP,self.h,PAYLOAD,CACHE).envelope_id,r.envelope_id)
        self.assertTrue(self.s.audit()['valid'])
    def test_payload_cache_not_stored_plain(self):
        self.commit()
        for row in self.s.connection.execute('SELECT encrypted_bytes FROM envelopes'):
            self.assertNotIn(PAYLOAD,row[0]);self.assertNotIn(CACHE,row[0])
        raw=self.s.connection.execute('SELECT encrypted_cache FROM local_commit_meta').fetchone()[0]
        self.assertNotIn(CACHE,raw);self.assertNotIn(PAYLOAD,raw)
    def test_committed_retry_no_rng_no_new_reservation(self):
        r=self.commit();n=self.count('issued_nonces')
        def broken(n):raise AssertionError('RNG must not be reached on retry')
        self.w=self.writer(random_source=broken)
        self.assertEqual(self.commit(),r);self.assertEqual(self.count('issued_nonces'),n)
    def test_committed_retry_after_another_operation(self):
        r=self.commit();h=dict(self.h);h[7]=2;h[8]=r.envelope_id
        self.commit(b'2'*16,h,cache=b'newer cache');self.assertEqual(self.commit(),r)
    def test_retry_input_mismatch(self):self.commit();self.store_reject('OPERATION_CONFLICT',lambda:self.commit(cache=b'different'))
    def test_new_writer_reopen_same_operation(self):
        r=self.commit();self.s.close();self.s=Store.open(self.path,allow_unpatched_sqlite=True);self.addCleanup(self.s.close);self.w=self.writer()
        self.assertEqual(self.commit(),r)
    def test_read_not_committed(self):self.assertIsNone(self.w.read_committed(OP,self.h,PAYLOAD,CACHE))
    def test_random_failure_before_reservation(self):
        self.w=self.writer(random_source=lambda n:None);self.reject('RNG_FAILURE',self.commit)
        self.assertEqual(self.count('issued_nonces'),0);self.assertEqual(self.count('envelopes'),0)
    def test_failure_after_first_reservation_burns_nonce(self):
        def observe(stage):
            if stage=='crypto.after_content_reservation':raise RuntimeError('injected')
        self.w=self.writer(observer=observe);self.reject('CRYPTO_ABORTED',self.commit)
        self.assertEqual(self.count('issued_nonces'),1);self.assertEqual(self.count('envelopes'),0)
        self.w=self.writer();self.commit();self.assertEqual(self.count('issued_nonces'),4)
    def test_failure_at_second_rng_keeps_first_nonce(self):
        count=0
        def source(n):
            nonlocal count
            count+=1
            return b'n'*n if count==1 else None
        self.w=self.writer(random_source=source);self.reject('RNG_FAILURE',self.commit)
        self.assertEqual(self.count('issued_nonces'),1);self.assertEqual(self.count('envelopes'),0)
    def test_repeated_nonce_rejected_on_next_commit(self):
        self.w=self.writer(random_source=lambda n:b'n'*n);r=self.commit();h=dict(self.h);h[7]=2;h[8]=r.envelope_id
        self.store_reject('NONCE_REUSED',lambda:self.commit(b'2'*16,h))
        self.assertEqual(self.count('envelopes'),1)
    def test_key_role_reuse(self):self.reject('KEY_ROLE_REUSE',lambda:self.m.CryptoStoreWriter(self.p,self.s,EPOCH,SIGN,EPOCH))
    def test_invalid_header_no_reserve(self):
        h=dict(self.h);h[7]=0;self.reject('OBJECT_SCHEMA',lambda:self.commit(h=h));self.assertEqual(self.count('issued_nonces'),0)
    def test_app_mismatch_no_reserve(self):
        from par_crypto.primitives import hashed
        h=dict(self.h);h[0]='org.other.notes';h[5]=hashed('device-id',[h[0],self.p.sign_public(SIGN)])
        self.reject('STORE_CONTEXT_MISMATCH',lambda:self.commit(h=h));self.assertEqual(self.count('issued_nonces'),0)
    def test_control_head_mismatch_no_reserve(self):
        h=dict(self.h);h[13]=b'z'*32;self.reject('STORE_CONTEXT_MISMATCH',lambda:self.commit(h=h));self.assertEqual(self.count('issued_nonces'),0)
    def test_wrong_epoch_secret_replay(self):
        self.commit();self.w=self.m.CryptoStoreWriter(self.p,self.s,b'X'*32,SIGN,LOCAL)
        self.reject('AEAD_INVALID',self.commit)
    def test_wrong_local_secret_not_old_operation(self):
        self.commit();self.w=self.m.CryptoStoreWriter(self.p,self.s,EPOCH,SIGN,b'X'*32)
        self.store_reject('OPERATION_CONFLICT',self.commit)
    def test_envelope_corruption_detected_on_replay(self):
        self.commit();c=self.s.connection;row=c.execute('SELECT encrypted_bytes FROM envelopes').fetchone();raw=bytearray(row[0]);raw[-1]^=1
        c.execute('UPDATE envelopes SET encrypted_bytes=?',(bytes(raw),));self.reject('COMMITTED_DATA_INVALID',self.commit)
    def test_receipt_corruption_detected_on_replay(self):
        self.commit();c=self.s.connection;raw=bytearray(c.execute('SELECT receipt_encrypted FROM commit_ledger').fetchone()[0]);raw[-1]^=1
        c.execute('UPDATE commit_ledger SET receipt_encrypted=?',(bytes(raw),));self.reject('AEAD_INVALID',self.commit)
    def test_cache_corruption_detected_on_replay(self):
        self.commit();c=self.s.connection;raw=bytearray(c.execute('SELECT encrypted_cache FROM local_commit_meta').fetchone()[0]);raw[-1]^=1
        c.execute('UPDATE local_commit_meta SET encrypted_cache=?',(bytes(raw),));self.reject('AEAD_INVALID',self.commit)
    def test_response_lost_after_commit(self):
        def observe(stage):
            if stage=='commit.after_commit':raise RuntimeError('response lost')
        self.s.observer=observe;self.store_reject('LOCAL_OUTCOME_UNKNOWN',self.commit);self.s.observer=None
        self.assertIsNotNone(self.commit());self.assertEqual(self.count('issued_nonces'),3)
    def test_restore_decrypt_but_write_denied(self):
        from par_store.recovery import restore_snapshot
        r=self.commit();backup=Path(self.tmp.name)/'backup';self.s.export_snapshot(backup)
        dest=Path(self.tmp.name)/'restored';restore_snapshot(backup,dest,allow_unpatched_sqlite=True)
        with Store.open(dest,allow_unpatched_sqlite=True) as restored:
            w=self.m.CryptoStoreWriter(self.p,restored,EPOCH,SIGN,LOCAL)
            self.assertEqual(w.read_committed(OP,self.h,PAYLOAD,CACHE),r)
            self.store_reject('RESTORE_READ_ONLY',lambda:w.commit(OP,self.h,PAYLOAD,CACHE))
    def test_intent_is_keyed_not_plain_hash(self):
        import hashlib
        self.commit();digest=self.s.connection.execute('SELECT input_digest FROM commit_ledger').fetchone()[0]
        self.assertNotEqual(digest,hashlib.sha256(PAYLOAD).digest());self.assertNotEqual(digest,hashlib.sha256(encode([self.h,PAYLOAD,CACHE])).digest())

def crash_case(stage,committed,nonces):
    def test(self):
        self.s.close()
        cmd=[sys.executable,'-I','-S','-B',str(ROOT/'tests/product/g0-crypto/crypto_crash_child.py'),str(self.path),stage]
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(proc.returncode,-signal.SIGKILL,(proc.stdout,proc.stderr));self.assertIn(stage,proc.stdout)
        self.s=Store.open(self.path,allow_unpatched_sqlite=True);self.addCleanup(self.s.close);self.w=self.writer()
        self.assertEqual(self.count('envelopes'),int(committed));self.assertEqual(self.count('issued_nonces'),nonces)
        before=[r[0] for r in self.s.connection.execute('SELECT nonce FROM issued_nonces')]
        r=self.commit();self.assertIsNotNone(r);self.assertTrue(self.s.audit()['valid'])
        self.assertEqual(self.count('issued_nonces'),nonces+(0 if committed else 3))
        self.assertTrue(set(before)<=set(r[0] for r in self.s.connection.execute('SELECT nonce FROM issued_nonces')))
    return test
for stage,committed,n in [('crypto.after_content_reservation',False,1),('crypto.after_content_seal',False,1),('crypto.before_store_commit',False,3),('commit.after_envelope',False,3),('commit.before_commit',False,3),('commit.after_commit',True,3)]:
    setattr(StoreCryptoTests,'test_sigkill_'+stage.replace('.','_'),crash_case(stage,committed,n))

class StoreBoundaryTests(StoreCryptoTests):
    # Only these methods run on this class; inherited tests retain their original IDs.
    def test_header_input_frozen_before_observer(self):
        import copy
        original=copy.deepcopy(self.h)
        def observe(stage):
            if stage=='crypto.after_content_reservation':
                self.h[13]=b'Z'*32;self.h[10].append(b'Z'*32)
        self.w=self.writer(observer=observe);r=self.commit()
        self.assertEqual(self.w.read_committed(OP,original,PAYLOAD,CACHE),r)
    def test_stale_writer_fence_cannot_commit(self):
        self.s.rotate_fence();self.store_reject('FENCE_STALE',self.commit);self.assertEqual(self.count('envelopes'),0)
    def test_reentrant_observer_cannot_insert_second_operation(self):
        def observe(stage):
            if stage=='crypto.after_content_reservation':self.commit(b'2'*16)
        self.w=self.writer(observer=observe);self.reject('CRYPTO_ABORTED',self.commit);self.assertEqual(self.count('envelopes'),0)
# Avoid running the inherited cases a second time under different test IDs.
for _name in list(vars(StoreCryptoTests)):
    if _name.startswith('test_'):setattr(StoreBoundaryTests,_name,None)
