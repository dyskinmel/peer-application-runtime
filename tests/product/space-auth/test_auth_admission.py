from auth_support import *
class AdmissionTests(AuthTest):
    def setup_request(self):
        m=self.require('admission');d=self.s.devices[0];nonce=h('request')
        raw=m.create_join(self.p,d['seed'],self.s.app,self.s.space,d['cert'],nonce,2)
        req=m.verify_join(self.p,self.s.app,self.s.space,d['cert'],raw,nonce,2)
        return m,raw,req
    def test_request_proves_device_only(self):
        m,raw,req=self.setup_request();self.assertEqual(req.device_id,self.s.devices[0]['id']);self.assertEqual(req.role,2)
    def test_admission_is_not_membership(self):
        m,raw,req=self.setup_request();st=self.state();old=st.head
        adm=m.issue_admission(st,self.s.owner,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=2)
        got=m.verify_admission(self.p,st.authority_public,req,adm)
        self.assertEqual(got.scope,'BOUNDED_CONTROL_RETRIEVAL_ONLY');self.assertEqual(got.minimum_sequence,2);self.assertEqual(st.head,old)
    def test_request_nonce_mismatch(self):
        m,raw,req=self.setup_request();self.reject('JOIN_CONTEXT',lambda:m.verify_join(self.p,self.s.app,self.s.space,self.s.devices[0]['cert'],raw,h('other'),2))
    def test_request_role_mismatch(self):
        m,raw,req=self.setup_request();self.reject('JOIN_CONTEXT',lambda:m.verify_join(self.p,self.s.app,self.s.space,self.s.devices[0]['cert'],raw,h('request'),1))
    def test_request_space_mismatch(self):
        m,raw,req=self.setup_request();self.reject('JOIN_CONTEXT',lambda:m.verify_join(self.p,self.s.app,h('other'),self.s.devices[0]['cert'],raw,h('request'),2))
    def test_request_app_mismatch(self):
        m,raw,req=self.setup_request();self.reject('JOIN_CONTEXT',lambda:m.verify_join(self.p,'other.example',self.s.space,self.s.devices[0]['cert'],raw,h('request'),2))
    def test_request_certificate_substitution(self):
        m,raw,req=self.setup_request();self.reject('JOIN_CONTEXT',lambda:m.verify_join(self.p,self.s.app,self.s.space,self.s.devices[1]['cert'],raw,h('request'),2))
    def test_request_signature_required(self):
        m,raw,req=self.setup_request();o=decode(raw);o[2]=b'0'*64
        self.reject('CRYPTO_INVALID',lambda:m.verify_join(self.p,self.s.app,self.s.space,self.s.devices[0]['cert'],encode(o),h('request'),2))
    def test_create_wrong_device_secret(self):
        m=self.require('admission');self.reject('JOIN_CONTEXT',lambda:m.create_join(self.p,h('different'),self.s.app,self.s.space,self.s.devices[0]['cert'],h('request'),2))
    def test_issue_wrong_owner(self):
        m,raw,req=self.setup_request();st=self.state();self.reject('AUTHORITY_MISMATCH',lambda:m.issue_admission(st,self.s.owner1,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=2))
    def test_admission_wrong_trusted_owner(self):
        m,raw,req=self.setup_request();st=self.state();a=m.issue_admission(st,self.s.owner,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=2)
        self.reject('AUTHORITY_MISMATCH',lambda:m.verify_admission(self.p,self.p.sign_public(self.s.owner1),req,a))
    def test_admission_tampered_signature(self):
        m,raw,req=self.setup_request();st=self.state();a=m.issue_admission(st,self.s.owner,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=2);o=decode(a);o[2]=b'0'*64
        self.reject('CRYPTO_INVALID',lambda:m.verify_admission(self.p,st.authority_public,req,encode(o)))
    def test_minimum_sequence_cannot_be_zero(self):
        m,raw,req=self.setup_request();self.reject('ADMISSION_SEQUENCE',lambda:m.issue_admission(self.state(),self.s.owner,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=0))
    def test_join_duplicate_not_global_once_claim(self):
        m,raw,req=self.setup_request();again=m.verify_join(self.p,self.s.app,self.s.space,self.s.devices[0]['cert'],raw,h('request'),2);self.assertEqual(again,req)
    def test_opaque_keeper_request_allowed_not_read_grant(self):
        m=self.require('admission');d=self.s.devices[2];raw=m.create_join(self.p,d['seed'],self.s.app,self.s.space,d['cert'],h('k'),3)
        q=m.verify_join(self.p,self.s.app,self.s.space,d['cert'],raw,h('k'),3);self.assertEqual(q.role,3)

def field_change(key,value):
    def test(self):
        m,raw,req=self.setup_request();st=self.state();a=m.issue_admission(st,self.s.owner,self.s.devices[0]['cert'],raw,h('request'),2,minimum_sequence=2);o=decode(a);b=decode(o[0]);b[key]=value
        a=objects._signed(self.p,self.s.owner,'admission-sign',b);self.reject('ADMISSION_CONTEXT',lambda:m.verify_admission(self.p,st.authority_public,req,a))
    return test
for key,value in [(0,'other.example'),(1,h('other')),(2,h('otherdevice')),(3,h('othercert')),(4,h('othernonce')),(6,1)]:
    setattr(AdmissionTests,'test_admission_context_'+str(key),field_change(key,value))
