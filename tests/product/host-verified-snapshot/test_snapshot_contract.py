import copy, json, os, pickle, threading
from snapshot_support import SnapshotTest,h

class SnapshotContract(SnapshotTest):
    def test_exact_success_reused(self):
        self.assertIsNone(self.verify());self.assertIsNone(self.verify());s=self.p.statistics()
        self.assertEqual((s['attempts'],s['backend_calls'],s['hits'],s['entries']),(2,1,1,1))
    def test_full_is_default(self):
        p=self.m.VerificationProvider(self.base)
        try:
            p.verify(self.pk,self.msg,self.sig);p.verify(self.pk,self.msg,self.sig)
            self.assertEqual((p.statistics()['backend_calls'],p.statistics()['hits'],p.statistics()['entries']),(2,0,0))
        finally:p.close()
    def test_different_message_rejected(self):
        self.verify();self.err('SIGNATURE_INVALID',lambda:self.verify(msg=self.msg+b'x'));self.assertEqual(self.p.statistics()['entries'],0)
    def test_different_public_key_rejected(self):
        self.verify();self.err('SIGNATURE_INVALID',lambda:self.verify(pk=self.base.sign_public(h('other'))))
    def test_different_signature_rejected(self):
        self.verify();self.err('SIGNATURE_INVALID',lambda:self.verify(sig=bytes([self.sig[0]^1])+self.sig[1:]))
    def test_invalid_not_negative_cached(self):
        for _ in range(2):self.err('SIGNATURE_INVALID',lambda:self.verify(msg=b'wrong'))
        self.assertEqual(self.p.statistics()['backend_calls'],2)
    def test_valid_new_message_is_miss(self):
        self.verify();msg=b'other';self.verify(msg=msg,sig=self.base.sign(self.seed,msg));self.assertEqual(self.p.statistics()['entries'],2)
    def test_domain_prefix_is_key_material(self):
        self.verify();self.err('SIGNATURE_INVALID',lambda:self.verify(msg=b'other-domain/'+self.msg))
    def test_empty_message_can_be_verified(self):
        sig=self.base.sign(self.seed,b'');self.verify(msg=b'',sig=sig);self.verify(msg=b'',sig=sig);self.assertEqual(self.p.statistics()['hits'],1)
    def test_no_mutable_message_key(self):self.err('INVALID_INPUT',lambda:self.verify(msg=bytearray(self.msg)))
    def test_no_mutable_signature(self):self.err('INVALID_INPUT',lambda:self.verify(sig=bytearray(self.sig)))
    def test_no_mutable_public_key(self):self.err('INVALID_INPUT',lambda:self.verify(pk=bytearray(self.pk)))
    def test_short_key(self):self.err('INVALID_INPUT',lambda:self.verify(pk=self.pk[:-1]))
    def test_short_signature(self):self.err('INVALID_INPUT',lambda:self.verify(sig=self.sig[:-1]))
    def test_oversize_message_rejected_before_backend(self):
        self.err('INVALID_INPUT',lambda:self.verify(msg=b'x'*1048577));self.assertEqual(self.p.statistics()['backend_calls'],0)
    def test_stats_cannot_poison_cache(self):
        self.verify();s=self.p.statistics();s['entries']=10000;s['hits']=10000;self.assertEqual(self.p.statistics()['entries'],1);self.verify();self.assertEqual(self.p.statistics()['hits'],1)
    def test_stats_no_raw_inputs(self):
        self.verify();s=json.dumps(self.p.statistics());self.assertNotIn(self.msg.decode(),s);self.assertNotIn(self.sig.hex(),s);self.assertNotIn(self.pk.hex(),s)
    def test_provider_identity_copy(self):
        d=self.p.identity;d['sha256']='bad';self.verify();self.assertEqual(self.p.identity['sha256'],self.base.identity['sha256'])
    def test_provider_identity_change_fails_closed(self):
        self.verify();old=self.base.identity['sha256'];self.base.identity['sha256']='f'*64
        self.err('PROVIDER_CHANGED',self.verify);self.base.identity['sha256']=old
        self.err('PROVIDER_CHANGED',self.verify);self.assertEqual(self.p.statistics()['entries'],0)
    def test_verify_callable_swap_fails_closed(self):
        self.verify();self.base.verify=lambda *a:None;self.err('PROVIDER_CHANGED',self.verify)
    def test_foreign_thread_refused(self):
        self.verify();errors=[]
        def worker():
            try:self.verify()
            except Exception as e:errors.append(getattr(e,'code',None))
        t=threading.Thread(target=worker);t.start();t.join();self.assertEqual(errors,['OWNER_REQUIRED']);self.verify();self.assertEqual(self.p.statistics()['hits'],1)
    def test_no_pickle(self):
        self.verify()
        with self.assertRaises(TypeError):pickle.dumps(self.p)
    def test_no_deepcopy(self):
        with self.assertRaises(TypeError):copy.deepcopy(self.p)
    def test_explicit_close_clears_and_rejects(self):
        self.verify();self.p.close();self.err('CLOSED',self.verify);self.assertEqual(self.p.statistics()['entries'],0)
    def test_invalid_mode(self):self.err('CACHE_CONFIG',lambda:self.m.VerificationProvider(self.base,mode='unchecked'))
    def test_arbitrary_provider_rejected(self):self.err('PROVIDER_REQUIRED',lambda:self.m.VerificationProvider(object()))
    def test_signing_not_memoized(self):
        self.assertEqual(self.p.sign(self.seed,self.msg),self.sig);self.assertEqual(self.p.sign(self.seed,self.msg),self.sig);self.assertEqual(self.p.statistics()['entries'],0)
    def test_encryption_not_memoized(self):
        key=h('key');nonce=b'a'*24;c=self.p.seal(key,nonce,b'aad',b'plain');self.assertEqual(self.p.open(key,nonce,b'aad',c),b'plain');self.assertEqual(self.p.statistics()['entries'],0)
    def test_other_crypto_methods_forward(self):
        x=h('x');y=h('y');self.assertEqual(self.p.dh_public(x),self.base.dh_public(x));self.assertEqual(self.p.dh(x,self.p.dh_public(y)),self.base.dh(x,self.base.dh_public(y)))
        ct=self.p.seal_ietf(x,b'b'*12,b'',b'test');self.assertEqual(self.p.open_ietf(x,b'b'*12,b'',ct),b'test')
