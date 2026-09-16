from auth_support import *
def change(s,b,author=0,**kw):
    d=s.devices[author];payload=b'opaque inner change, not validated by Automerge';obj=h('doc');schema=h('schema')
    hdr={0:s.app,1:s.space,2:b['body'][3],3:obj,4:1,5:d['id'],6:h('actor-generation')[:16],7:1,8:None,9:schema,10:[],11:len(payload),12:h('inner hash'),13:control_id(b['raw']),14:1,15:0}
    for k,v in kw.items():hdr[int(k)]=v
    raw=objects.seal_change(s.p,b['secret'],d['seed'],hdr,payload,h('change-nonce-'+str(author))[:24])
    return raw,hdr,payload
class ReceiverTests(AuthTest):
    def start(self):
        self.require('receiver');st,b=active_state(self);raw,hdr,plain=change(self.s,b);return st,b,raw,hdr,plain
    def receive(self,st,raw,cert=None,**kw):
        return self.require('receiver').receive_change(st,raw,cert or self.s.devices[0]['cert'],expected_object=kw.get('obj',h('doc')),expected_schema=kw.get('schema',h('schema')))
    def test_valid_change_is_candidate_not_apply(self):
        st,b,raw,hdr,plain=self.start();r=self.receive(st,raw);self.assertEqual(r.payload,plain);self.assertFalse(r.inner_validated);self.assertFalse(r.applied);self.assertEqual(r.envelope_id,objects.envelope_id(raw))
    def test_reader_signature_is_not_write_permission(self):
        st,b,raw,hdr,plain=self.start();raw,_,_=change(self.s,b,1);self.reject('NOT_AUTHORIZED',lambda:self.receive(st,raw,self.s.devices[1]['cert']))
    def test_keeper_cannot_write(self):
        st,b,raw,hdr,plain=self.start();raw,_,_=change(self.s,b,2);self.reject('NOT_AUTHORIZED',lambda:self.receive(st,raw,self.s.devices[2]['cert']))
    def test_expected_object_binding(self):
        st,b,raw,hdr,plain=self.start();self.reject('CONTEXT_MISMATCH',lambda:self.receive(st,raw,obj=h('other')))
    def test_expected_schema_binding(self):
        st,b,raw,hdr,plain=self.start();self.reject('CONTEXT_MISMATCH',lambda:self.receive(st,raw,schema=h('other')))
    def test_signature_corruption(self):
        st,b,raw,hdr,plain=self.start();o=decode(raw);o[3]=b'0'*64;self.reject('CRYPTO_INVALID',lambda:self.receive(st,encode(o)))
    def test_ciphertext_re_signed_but_bad_aead(self):
        st,b,raw,hdr,plain=self.start();o=decode(raw);o[2]=o[2][:-1]+bytes([o[2][-1]^1]);o[3]=self.p.sign(self.s.devices[0]['seed'],domain('envelope-sign',[o[0],o[1],o[2]]))
        self.reject('CRYPTO_INVALID',lambda:self.receive(st,encode(o)))
    def test_unknown_control(self):
        st,b,raw,hdr,plain=self.start();raw,_,_=change(self.s,b,**{'13':h('unknown')});self.reject('CONTROL_REQUIRED',lambda:self.receive(st,raw))
    def test_wrong_epoch_for_claimed_control(self):
        st,b,raw,hdr,plain=self.start();raw,_,_=change(self.s,b,**{'2':2});self.reject('CONTEXT_MISMATCH',lambda:self.receive(st,raw))
    def test_wrong_author_certificate(self):
        st,b,raw,hdr,plain=self.start();self.reject('CERTIFICATE_BINDING',lambda:self.receive(st,raw,self.s.devices[1]['cert']))
    def test_pending_control_prevents_candidate(self):
        st,b,raw,hdr,plain=self.start();st.observe(self.s.raw(self.s.next(b['raw'])));self.reject('MEMBERSHIP_REQUIRED',lambda:self.receive(st,raw))
    def test_old_epoch_is_rebase_not_apply(self):
        st,b,raw,hdr,plain=self.start();c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('nextsecret'));st.observe(c['raw']);st.provide_membership(c['pages'])
        self.reject('REBASE_REQUIRED',lambda:self.receive(st,raw))
    def test_revoked_old_valid_change_remains_rebase_candidate(self):
        st,b,raw,hdr,plain=self.start();c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('nextsecret'),entries=self.s.entries[1:]);st.observe(c['raw']);st.provide_membership(c['pages'])
        self.reject('REBASE_REQUIRED',lambda:self.receive(st,raw))
    def test_bad_signature_is_not_mislabeled_rebase(self):
        st,b,raw,hdr,plain=self.start();c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('nextsecret'));st.observe(c['raw']);st.provide_membership(c['pages']);o=decode(raw);o[3]=b'0'*64
        self.reject('CRYPTO_INVALID',lambda:self.receive(st,encode(o)))
    def test_older_control_same_epoch_can_be_used(self):
        st,b,raw,hdr,plain=self.start();st.observe(self.s.raw(self.s.next(b['raw'])));st.provide_membership(b['pages']);self.assertEqual(self.receive(st,raw).payload,plain)
    def test_candidate_recheck_after_control_change(self):
        st,b,raw,hdr,plain=self.start();r=self.receive(st,raw);st.observe(self.s.raw(self.s.next(b['raw'])));st.provide_membership(b['pages']);self.reject('STALE_DECISION',lambda:r.recheck(st))
    def test_candidate_recheck_same_state(self):
        st,b,raw,hdr,plain=self.start();self.assertIsNone(self.receive(st,raw).recheck(st))
    def test_candidate_payload_is_not_in_repr(self):
        st,b,raw,hdr,plain=self.start();self.assertNotIn(plain.decode(),repr(self.receive(st,raw)))
    def test_seed_wait_on_new_epoch(self):
        st,b,raw,hdr,plain=self.start();c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('nextsecret'));st.observe(c['raw']);st.provide_membership(c['pages']);new,_,_=change(self.s,c)
        self.reject('EPOCH_PENDING',lambda:self.receive(st,new))
