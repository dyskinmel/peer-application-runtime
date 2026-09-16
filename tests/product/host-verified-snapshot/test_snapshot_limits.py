from snapshot_support import SnapshotTest,h

class SnapshotLimits(SnapshotTest):
    def test_entry_eviction_keeps_acceptance(self):
        self.make(max_entries=1);self.verify();m=b'2';s=self.base.sign(self.seed,m);self.verify(msg=m,sig=s);self.verify();d=self.p.statistics();self.assertEqual((d['entries'],d['backend_calls'],d['evictions']),(1,3,2))
    def test_lru_access_not_fifo(self):
        self.make(max_entries=2);self.verify();m=b'2';s=self.base.sign(self.seed,m);self.verify(msg=m,sig=s);self.verify();n=b'3';self.verify(msg=n,sig=self.base.sign(self.seed,n));self.verify();self.assertEqual(self.p.statistics()['hits'],2)
    def test_byte_capacity_falls_back(self):
        self.make(max_key_bytes=97);self.verify();self.verify();self.assertEqual(self.p.statistics()['backend_calls'],2);self.assertEqual(self.p.statistics()['entries'],0)
    def test_byte_capacity_evicts(self):
        self.make(max_key_bytes=200);self.verify();m=b'x'*70;self.verify(msg=m,sig=self.base.sign(self.seed,m));d=self.p.statistics();self.assertLessEqual(d['key_bytes'],200);self.assertEqual(d['entries'],1)
    def test_oversize_valid_not_cached(self):
        self.make(max_message_bytes=8);self.verify();self.verify();self.assertEqual(self.p.statistics()['hits'],0);self.assertEqual(self.p.statistics()['bypasses'],2)
    def test_exact_message_limit(self):
        self.make(max_message_bytes=len(self.msg));self.verify();self.verify();self.assertEqual(self.p.statistics()['hits'],1)
    def test_budget_boolean_invalid(self):self.err('CACHE_CONFIG',lambda:self.make(max_entries=True))
    def test_budget_zero_invalid(self):self.err('CACHE_CONFIG',lambda:self.make(max_entries=0))
    def test_budget_over_max_invalid(self):self.err('CACHE_CONFIG',lambda:self.make(max_key_bytes=64*1024*1024+1))
    def test_negative_message_limit(self):self.err('CACHE_CONFIG',lambda:self.make(max_message_bytes=-1))
    def test_invalidate_cold(self):
        self.verify();self.p.invalidate('operator');self.verify();self.assertEqual(self.p.statistics()['backend_calls'],2)
    def test_scope_same_preserves(self):
        self.p.observe_scope(b'a');self.verify();self.p.observe_scope(b'a');self.verify();self.assertEqual(self.p.statistics()['hits'],1)
    def test_scope_change_invalidates(self):
        self.p.observe_scope(b'a');self.verify();self.p.observe_scope(b'b');self.verify();self.assertEqual(self.p.statistics()['backend_calls'],2)
    def test_scope_size_bounded(self):self.err('INVALID_INPUT',lambda:self.p.observe_scope(b'x'*4097))
    def test_scope_mutable_rejected(self):self.err('INVALID_INPUT',lambda:self.p.observe_scope(bytearray(b'a')))
    def test_full_verification_context_bypasses_warm(self):
        self.verify()
        with self.p.full_verification():self.verify();self.verify();self.assertEqual(self.p.statistics()['entries'],0)
        self.verify();self.assertEqual(self.p.statistics()['backend_calls'],4)
    def test_nested_full_context(self):
        with self.p.full_verification():
            with self.p.full_verification():self.verify()
            self.verify()
        self.verify();self.verify();self.assertEqual(self.p.statistics()['hits'],1)
    def test_failure_inside_full_does_not_warm(self):
        self.verify()
        try:
            with self.p.full_verification():self.verify();raise RuntimeError('injected')
        except RuntimeError:pass
        self.assertEqual(self.p.statistics()['entries'],0);self.verify();self.assertEqual(self.p.statistics()['backend_calls'],3)
    def test_new_instance_starts_cold(self):
        self.verify();self.p.close();self.p=self.m.VerificationProvider(self.base,mode='signatures');self.verify();self.assertEqual(self.p.statistics()['hits'],0)
    def test_repeated_invalid_clears_prior_success(self):
        self.verify();self.err('SIGNATURE_INVALID',lambda:self.verify(msg=b'bad'));self.verify();self.assertEqual(self.p.statistics()['backend_calls'],3)
