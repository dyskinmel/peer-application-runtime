from dataclasses import replace
from retire_support import RetireTest,h,pr
from par_crypto.primitives import domain
from par_wire.codec import encode,decode

class RetireContract(RetireTest):
    def setUp(self):
        super().setUp();self.token=self.begin_index();self.req=self.retirement_request()
    def body(self,raw):return decode(decode(raw)[0])
    def resign(self,body,label,seed):
        b=encode(body);return encode({0:b,1:self.p.sign(seed,domain('keeper-upload-retire-local/'+label,[b]))})
    def check(self,raw):return self.ret.check_request(self.p,raw,self.beginraw,self.kp,self.authority)
    def test_valid_bound_request(self):self.assertEqual(self.check(self.req)[2][5],self.token)
    def test_request_signature_tamper(self):
        raw=bytearray(self.req);raw[-1]^=1;self.err(None,lambda:self.check(bytes(raw)))
    def test_old_capability_is_not_retirement_permission(self):self.err(None,lambda:self.ret.make_request(self.p,self.cs,self.cap,h('op')))
    def test_other_subject_cannot_request(self):
        self.err(None,lambda:self.ret.make_request(self.p,h('other'),self.body(self.req)[2],h('op')))
    def test_other_issuer_cannot_grant(self):
        self.err(None,lambda:self.ret.issue_grant(self.p,h('other'),self.authority,self.kp,self.beginraw,h('g')))
    def test_current_authority_is_required(self):
        self.change_authority();self.err(None,lambda:self.check(self.req))
    def test_new_authority_can_retire_old_stage(self):
        self.change_authority();self.assertEqual(self.check(self.retirement_request())[2][5],self.token)
    def test_different_keeper_rejected(self):
        self.err(None,lambda:self.ret.check_request(self.p,self.req,self.beginraw,h('other'),self.authority))
    def test_different_stage_rejected(self):
        self.begin_index();self.err(None,lambda:self.ret.check_request(self.p,self.req,self.beginraw,self.kp,self.authority))
    def test_different_app_rejected(self):
        a=replace(self.authority,app='org.other.test');self.err(None,lambda:self.retirement_request(authority=a))
    def test_different_space_rejected(self):self.err(None,lambda:self.retirement_request(authority=replace(self.authority,space=h('wrong'))))
    def test_authority_rollback_rejected(self):self.err(None,lambda:self.retirement_request(authority=replace(self.authority,sequence=0)))
    def test_same_sequence_different_head_rejected(self):self.err(None,lambda:self.retirement_request(authority=replace(self.authority,head=h('same-sequence'))))
    def test_changed_issuer_supported_only_in_new_authority(self):
        seed=h('new-issuer');a=replace(self.authority,issuer=self.p.sign_public(seed),sequence=2,head=h('new'))
        raw=self.retirement_request(authority=a,issuer_seed=seed)
        self.assertEqual(self.ret.check_request(self.p,raw,self.beginraw,self.kp,a)[2][5],self.token)
    def test_operation_id_changes_request_identity(self):
        other=self.retirement_request(operation=h('another'))
        self.assertNotEqual(self.ret.request_id(self.p,self.req),self.ret.request_id(self.p,other))
    def test_explicit_acknowledgement_required(self):
        b=self.body(self.req);b[4]=False;self.err(None,lambda:self.check(self.resign(b,'request',self.cs)))
    def test_unknown_request_field_rejected(self):
        b=self.body(self.req);b[9]=1;self.err(None,lambda:self.check(self.resign(b,'request',self.cs)))
    def test_unknown_profile_rejected(self):
        b=self.body(self.req);b[1]='another';self.err(None,lambda:self.check(self.resign(b,'request',self.cs)))
    def test_boolean_version_rejected(self):
        b=self.body(self.req);b[0]=True;self.err(None,lambda:self.check(self.resign(b,'request',self.cs)))
    def test_missing_field_rejected(self):
        b=self.body(self.req);del b[3];self.err(None,lambda:self.check(self.resign(b,'request',self.cs)))
    def test_wrong_nonce_type_rejected(self):
        g=self.body(self.req)[2];self.err(None,lambda:self.ret.make_request(self.p,self.cs,g,'not-bytes'))
    def test_oversized_input_rejected(self):self.err(None,lambda:self.check(bytes(131073)))
    def test_wrong_domain_rejected(self):self.err(None,lambda:self.check(self.resign(self.body(self.req),'grant',self.cs)))
    def test_non_begin_origin_rejected(self):
        raw=self.cmd('progress',self.token)
        self.err(None,lambda:self.retirement_request(begin=raw))
