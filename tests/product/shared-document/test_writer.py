"""Real Store/crypto with a deliberately synthetic semantic port. Never CRDT evidence."""
import copy, hashlib, importlib.util, json, threading
from auth_store_support import AuthStoreTest,h
from par_crypto import objects
from product.wp04 import contracts as c

class ContractPort:
    def __init__(self):
        self.identity={'name':'@automerge/automerge','version':'3.4.1','kind':'contract-test-double','digest':'a'*64};self.calls=0;self.hook=None
    def validate(self,request):
        self.calls+=1
        if self.hook:self.hook()
        x=request['candidate']
        return {'profile':c.PROFILE,'requestDigest':c.request_digest(request),'engine':dict(self.identity),
                'changes':[{k:x[k] for k in ('actor','sequence','hash','dependencies')}],
                'appliedHashes':[r['hash'] for r in request['closure']]+[x['hash']], 'missing':[],
                'note':{'title':'contract fixture','body':'synthetic, not CRDT','titleConflicts':[]},'schema':'note-v1-local'}

class SharedWriterTests(AuthStoreTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp04.writer'),'guarded shared writer is not implemented')
        from product.wp04.writer import SharedWriter
        self.maker=SharedWriter;self.start();self.port=ContractPort();self.w=self.make()
    def make(self,**kw):
        return self.maker(self.writer(),self.port,app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),schema_id=h('schema'),allow_contract_double=kw.get('allow_contract_double',True))
    def request32(self,**kw):
        op,hdr,p,_=self.request(**kw);return op,hdr,p
    def reject32(self,fn,code=None):
        with self.assertRaises(Exception) as cm:fn()
        if code:self.assertEqual(getattr(cm.exception,'code',None),code)
    def test_no_engine_no_nonce_no_write(self):
        w=self.make(allow_contract_double=False)
        self.reject32(lambda:w.prepare(*self.request32()),'CORE_NOT_REAL');self.assertEqual(self.count('issued_nonces'),0);self.assertEqual(self.count('envelopes'),0)
    def test_contract_success_always_pending_not_applied(self):
        r=self.w.write(*self.request32());self.assertFalse(r['innerValidated']);self.assertFalse(r['applied']);self.assertTrue(r['localCommitted']);self.assertEqual(r['evidenceKind'],'CONTRACT_TEST_DOUBLE_REAL_STORE');self.assertEqual(self.count('envelopes'),1)
    def test_contract_report_not_shown_as_materialized_document(self):
        self.w.write(*self.request32());row=self.db._storage.connection.execute('select state from envelopes').fetchone();self.assertEqual(row[0],'pending')
    def test_bad_decoded_actor_before_nonce(self):
        old=self.port.validate
        def bad(req):r=old(req);r['changes'][0]['actor']='b'*64;return r
        self.port.validate=bad
        self.reject32(lambda:self.w.prepare(*self.request32()),'INNER_OUTER_MISMATCH');self.assertEqual(self.count('issued_nonces'),0)
    def test_dependency_missing_before_engine_and_nonce(self):
        op,hdr,p=self.request32();hdr[10]=[h('missing')]
        self.reject32(lambda:self.w.prepare(op,hdr,p),'DEPENDENCIES_MISSING');self.assertEqual(self.port.calls,0);self.assertEqual(self.count('issued_nonces'),0)
    def test_signed_dependency_read_and_decrypted(self):
        op,hdr,p=self.request32();r=self.w.write(op,hdr,p)
        op2,h2,p2=self.request32(op=2,sequence=2,previous=bytes.fromhex(r['commitId']));h2[12]=h('second-change');h2[10]=[hdr[12]]
        r2=self.w.write(op2,h2,p2);self.assertTrue(r2['localCommitted']);self.assertEqual(self.count('envelopes'),2)
    def test_previous_must_be_causal_dependency(self):
        r=self.w.write(*self.request32());n=self.count('issued_nonces')
        op,hdr,p=self.request32(op=2,sequence=2,previous=bytes.fromhex(r['commitId']));hdr[12]=h('second')
        self.reject32(lambda:self.w.prepare(op,hdr,p),'PREVIOUS_MISMATCH');self.assertEqual(self.count('issued_nonces'),n)
    def test_corrupt_dependency_signature_rejected(self):
        op,hdr,p=self.request32();r=self.w.write(op,hdr,p);row=self.db._storage.connection.execute('select encrypted_bytes from envelopes').fetchone();self.db._storage.connection.execute('update envelopes set encrypted_bytes=?',(row[0][:-1]+bytes([row[0][-1]^1]),))
        o,h2,p2=self.request32(op=2,sequence=2,previous=bytes.fromhex(r['commitId']));h2[12]=h('second');h2[10]=[hdr[12]]
        self.reject32(lambda:self.w.prepare(o,h2,p2),'STORE_VERIFICATION_FAILED')
    def test_dependency_other_doc_does_not_satisfy(self):
        op,hdr,p=self.request32();r=self.w.write(op,hdr,p)
        op2,h2,p2=self.request32(op=2);h2[3]=h('otherdoc');h2[12]=h('otherhash');h2[10]=[hdr[12]]
        w=self.maker(self.writer(),self.port,app_id=self.s.app,space_id=self.s.space,document_id=h('otherdoc'),schema_id=h('schema'),allow_contract_double=True)
        self.reject32(lambda:w.prepare(op2,h2,p2),'DEPENDENCIES_MISSING')
    def test_identity_change_during_call_rejected(self):
        self.port.hook=lambda:self.port.identity.update(digest='b'*64)
        self.reject32(lambda:self.w.prepare(*self.request32()),'CORE_IDENTITY_CHANGED');self.assertEqual(self.count('issued_nonces'),0)
    def test_authority_changes_during_core_call(self):
        self.port.hook=self.same_epoch
        self.reject32(lambda:self.w.prepare(*self.request32()),'OWNER_STATE_CHANGED');self.assertEqual(self.count('issued_nonces'),0)
    def test_authority_changes_after_prepare_commit_rejects(self):
        pending=self.w.prepare(*self.request32());n=self.count('issued_nonces');self.same_epoch()
        self.reject32(lambda:self.w.commit(pending),'STALE_DECISION');self.assertEqual(self.count('envelopes'),0);self.assertEqual(self.count('issued_nonces'),n)
    def test_replay_preserves_envelope_and_nonces(self):
        req=self.request32();a=self.w.write(*req);n=self.count('issued_nonces');b=self.w.write(*req)
        self.assertEqual(a,b);self.assertEqual(self.count('issued_nonces'),n);self.assertEqual(self.count('envelopes'),1)
    def test_commit_response_lost_can_recover_original(self):
        req=self.request32()
        def lost(stage):
            if stage=='commit.after_commit':raise OSError('lost')
        self.db.observer=lost;self.reject32(lambda:self.w.write(*req));self.db.observer=None
        n=self.count('issued_nonces');r=self.w.write(*req);self.assertTrue(r['localCommitted']);self.assertEqual(self.count('issued_nonces'),n)
    def test_same_operation_different_payload_refused(self):
        req=self.request32();self.w.write(*req);op,hdr,p=req;p2=p[:-1]+b'X';self.reject32(lambda:self.w.write(op,hdr,p2));self.assertEqual(self.count('envelopes'),1)
    def test_mutable_header_unchanged_mid_call(self):
        op,hdr,p=self.request32();self.port.hook=lambda:hdr.update({3:h('other')})
        pending=self.w.prepare(op,hdr,p);r=self.w.commit(pending)
        self.assertEqual(self.db._storage.connection.execute('select object_id from envelopes').fetchone()[0],h('doc'))
    def test_wrong_scope_before_core(self):
        op,hdr,p=self.request32();hdr[3]=h('other');self.reject32(lambda:self.w.prepare(op,hdr,p),'SCOPE_MISMATCH');self.assertEqual(self.port.calls,0)
    def test_wrong_owner_thread_rejected(self):
        errors=[]
        def run():
            try:self.w.prepare(*self.request32())
            except Exception as e:errors.append(getattr(e,'code',None))
        t=threading.Thread(target=run);t.start();t.join();self.assertEqual(errors,['WRONG_OWNER'])
    def test_reentrant_core_rejected(self):
        self.port.hook=lambda:self.w.prepare(*self.request32());self.reject32(lambda:self.w.prepare(*self.request32()),'REENTRANT_OPERATION');self.assertEqual(self.count('issued_nonces'),0)
    def test_close_refuses(self):
        self.w.close();self.reject32(lambda:self.w.prepare(*self.request32()),'CLOSED')
    def test_candidate_from_other_writer_refused(self):
        pending=self.w.prepare(*self.request32());self.reject32(lambda:self.make().commit(pending),'FOREIGN_PREPARED_CHANGE')
    def test_same_process_copy_not_transferable(self):
        from dataclasses import replace
        pending=self.w.prepare(*self.request32());bad=replace(pending,request_hash='b'*64)
        self.reject32(lambda:self.w.commit(bad),'PREPARED_CHANGED')
    def test_pending_candidate_no_persisted_applied_flag(self):
        pending=self.w.prepare(*self.request32());self.assertEqual(self.count('envelopes'),0);self.assertGreater(self.count('issued_nonces'),0)
    def test_waiting_has_no_new_operation_intent(self):
        op,hdr,p=self.request32();hdr[10]=[h('missing')];self.reject32(lambda:self.w.prepare(op,hdr,p));self.assertEqual(self.count('local_operation_intents'),0)
    def test_readonly_restore_refused(self):
        self.db._storage.connection.execute('update local_settings set read_only_restore=1');self.db._storage.restore_read_only=True
        self.reject32(lambda:self.w.prepare(*self.request32()))
    def test_broken_core_receipt_no_nonce(self):
        self.port.validate=lambda r:{'success':True};self.reject32(lambda:self.w.prepare(*self.request32()),'CORE_REPORT_INVALID');self.assertEqual(self.count('issued_nonces'),0)
    def test_backend_changed_inside_crypto_prepare_stops_single_write(self):
        original=self.w._writer.prepare
        def switch(*args):
            prepared=original(*args);self.port.identity['digest']='b'*64;return prepared
        self.w._writer.prepare=switch
        self.reject32(lambda:self.w.write(*self.request32()),'CORE_IDENTITY_CHANGED')
        self.assertEqual(self.count('envelopes'),0);self.assertGreater(self.count('issued_nonces'),0)
