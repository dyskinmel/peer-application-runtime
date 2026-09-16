from keeper_support import ContractTest,h,replace,decode,encode
class LeaseContract(ContractTest):
    def test_capability_roundtrip(self):
        c=self.cap();b=self.k.verify_capability(self.p,self.a,self.pk,c);self.assertEqual((b[4],b[5]),(self.sp,self.index))
    def test_capability_deterministic(self):self.assertEqual(self.cap(),self.cap())
    def test_wrong_authority_key(self):self.err('CAPABILITY_AUTH',lambda:self.k.verify_capability(self.p,replace(self.a,issuer=h('other')),self.pk,self.cap()))
    def test_stale_head(self):self.err('CAPABILITY_SCOPE',lambda:self.k.verify_capability(self.p,replace(self.a,head=h('other')),self.pk,self.cap()))
    def test_wrong_space(self):self.err('CAPABILITY_SCOPE',lambda:self.k.verify_capability(self.p,replace(self.a,space=h('other')),self.pk,self.cap()))
    def test_wrong_keeper(self):self.err('CAPABILITY_SCOPE',lambda:self.k.verify_capability(self.p,self.a,h('other'),self.cap()))
    def test_changed_signature(self):
        o=decode(self.cap());o[1]=bytes(64);self.err('CAPABILITY_AUTH',lambda:self.k.verify_capability(self.p,self.a,self.pk,encode(o)))
    def test_trailing_bytes(self):self.err('CONTRACT_SCHEMA',lambda:self.k.verify_capability(self.p,self.a,self.pk,self.cap()+b'\0'))
    def test_unknown_fields(self):
        o=decode(self.cap());o[7]=b'x';self.err('CONTRACT_SCHEMA',lambda:self.k.verify_capability(self.p,self.a,self.pk,encode(o)))
    def test_invalid_method(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(methods=('execute-shell',)))
    def test_duplicate_methods(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(methods=('get','get')))
    def test_empty_methods(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(methods=()))
    def test_zero_duration(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(maximum_seconds=0))
    def test_excess_duration(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(maximum_seconds=86401))
    def test_bool_duration(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(maximum_seconds=True))
    def test_wrong_seed_for_issuer(self):self.err('CAPABILITY_AUTH',lambda:self.k.issue_capability(self.p,h('bad'),self.a,self.pk,self.sp,self.index,('get',),30,h('nonce')))
    def test_short_nonce(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(nonce=b'x'))
    def test_bool_authority_sequence(self):self.err('CONTRACT_SCHEMA',lambda:self.cap(authority=replace(self.a,sequence=True)))
    def test_possession_request(self):
        cap=self.cap();call=self.k.make_call(self.p,self.subject,cap,'get',h('lease'),h('nonce'),h('object'))
        b=self.k.verify_call(self.p,self.a,self.pk,cap,call,'get',h('lease'),h('object'));self.assertEqual(b[7],h('nonce'))
    def test_request_wrong_subject(self):self.err('REQUEST_AUTH',lambda:self.k.make_call(self.p,h('stranger'),self.cap(),'get',h('lease'),h('nonce'),h('object')))
    def test_request_action_swap(self):
        cap=self.cap();c=self.k.make_call(self.p,self.subject,cap,'get',h('lease'),h('nonce'),None)
        self.err('REQUEST_SCOPE',lambda:self.k.verify_call(self.p,self.a,self.pk,cap,c,'release',h('lease'),None))
    def test_request_payload_swap(self):
        cap=self.cap();c=self.k.make_call(self.p,self.subject,cap,'get',h('lease'),h('nonce'),h('object'))
        self.err('REQUEST_SCOPE',lambda:self.k.verify_call(self.p,self.a,self.pk,cap,c,'get',h('lease'),h('different')))
    def test_request_lease_swap(self):
        cap=self.cap();c=self.k.make_call(self.p,self.subject,cap,'get',h('lease'),h('nonce'),None)
        self.err('REQUEST_SCOPE',lambda:self.k.verify_call(self.p,self.a,self.pk,cap,c,'get',h('another'),None))
    def test_readonly_cap_cannot_release(self):
        cap=self.cap(methods=('get',));c=self.k.make_call(self.p,self.subject,cap,'release',h('lease'),h('nonce'),None)
        self.err('METHOD_DENIED',lambda:self.k.verify_call(self.p,self.a,self.pk,cap,c,'release',h('lease'),None))
    def test_request_binds_grant_nonce(self):
        a=self.cap();b=self.cap(nonce=h('different'));c=self.k.make_call(self.p,self.subject,a,'get',h('lease'),h('nonce'),None)
        self.err('REQUEST_SCOPE',lambda:self.k.verify_call(self.p,self.a,self.pk,b,c,'get',h('lease'),None))
    def test_request_signature_change(self):
        g=self.cap();c=decode(self.k.make_call(self.p,self.subject,g,'get',h('lease'),h('nonce'),None));c[1]=bytes(64)
        self.err('REQUEST_AUTH',lambda:self.k.verify_call(self.p,self.a,self.pk,g,encode(c),'get',h('lease'),None))
    def test_keeper_clock_returns_bounded_tick(self):
        t=self.k.BootClock().sample();self.assertEqual(len(t.boot),32);self.assertIs(type(t.ns),int);self.assertGreaterEqual(t.ns,0)
    def test_frozen_retention_vector(self):
        import json
        from pathlib import Path
        from tools.generate_keeper_vector import generate
        root=Path(__file__).resolve().parents[3];path=root/'experiments/keeper-retention/fixtures/retention-receipt.json'
        self.assertTrue(path.is_file(),'frozen Keeper candidate vector missing')
        self.assertEqual(generate(),json.loads(path.read_text()))
