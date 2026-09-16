from unittest.mock import patch
from retire_control_support import ProtocolTest,h
class ContractTests(ProtocolTest):
    def test_profile_separate_and_methods_exact(self):
        self.assertNotEqual(self.proto.PROFILE,self.sc.PROFILE)
        self.assertEqual(set(self.proto.METHODS),{'proposal','status','reconcile_registration','retire','rebind'})
    def test_read_roundtrip(self):
        for action in ('proposal','status'):
            with self.subTest(action=action):self.assertEqual(self.ext_check(self.ext_request(action))[3],action)
    def test_dual_signature_roundtrip(self):
        d,_=self.partial();auth=self.retire_request(d)
        self.assertEqual(self.ext_check(self.ext_request('retire',d,auth))[5],auth)
    def test_mutation_without_authorization_rejected(self):
        self.err(None,lambda:self.ext_request('retire'))
    def test_read_rejects_extra_authorization(self):
        d,_=self.partial();self.err(None,lambda:self.ext_request('status',d,self.retire_request(d)))
    def test_unknown_method_rejected(self):
        for name in ('submit','select','cancel','eval','close','compact'):
            with self.subTest(method=name):self.err(None,lambda:self.ext_request(name))
    def test_wrong_origin_refused(self):
        d,_=self.partial();auth=self.retire_request(d,origin=h('wrong-origin'))
        self.err(None,lambda:self.ext_request('retire',d,auth))
    def test_wrong_job_refused(self):
        d,_=self.partial();auth=self.retire_request(d)
        self.err(None,lambda:self.ext_request('retire',self.descriptor(jid=h('other-job')),auth))
    def test_bad_inner_signature_refused(self):
        d,_=self.partial();auth=self.retire_request(d)
        self.err(None,lambda:self.ext_request('retire',d,auth[:-1]+bytes([auth[-1]^1])))
    def test_connection_replay_refused(self):
        self.err(None,lambda:self.ext_check(self.ext_request(),self.hello(challenge=h('different'))))
    def test_wrong_outer_key_refused(self):
        self.err(None,lambda:self.ext_request(seed=h('wrong-controller')))
    def test_rotation_allows_old_descriptor_with_new_dual_request(self):
        d,_=self.partial();ns=h('new-operator');np=self.p.sign_public(ns)
        self.ctl.replace_controller(np,2);auth=self.retire_request(d,operator=ns,revision=2)
        hi=self.hello(2,np);raw=self.ext_request('retire',d,auth,hi,ns)
        self.assertEqual(self.ext_check(raw,hi)[3],'retire')
    def test_legacy_request_not_accepted_as_extension(self):
        raw=self.sc.make_request(self.p,self.os,self.hello(),'progress',self.descriptor())
        self.err(None,lambda:self.ext_check(raw))
    def test_request_unknown_field_refused_even_when_signed(self):
        b=self.ext_check(self.ext_request());b[20]=1
        raw=self.proto.signed(self.p,self.os,'request',b,self.sc.MAX_REQUEST)
        self.err(None,lambda:self.ext_check(raw))
    def test_version_bool_refused(self):
        b=self.ext_check(self.ext_request());b[0]=True
        raw=self.proto.signed(self.p,self.os,'request',b,self.sc.MAX_REQUEST)
        self.err(None,lambda:self.ext_check(raw))
    def test_response_correspondence_and_strict_result(self):
        d,_=self.partial();req=self.ext_request('proposal',d)
        v={'kind':'proposal','job_id':self.jid().hex(),'descriptor_hash':self.sc.sha(d).hex(),'stage_state':'RECEIVING','controller_revision':1,'proposal':self.st.proposal(d),'product_qualified':False}
        raw=self.proto.make_response(self.p,self.ks,self.hello(),req,True,v)
        self.assertEqual(self.proto.check_response(self.p,self.kp,self.hello(),req,raw),v)
        wrong=dict(v);wrong['controller_revision']=True
        self.err(None,lambda:self.proto.make_response(self.p,self.ks,self.hello(),req,True,wrong))
    def test_response_replay_refused(self):
        req=self.ext_request('status');raw=self.proto.make_response(self.p,self.ks,self.hello(),req,False,'REJECTED')
        self.err(None,lambda:self.proto.check_response(self.p,self.kp,self.hello(challenge=h('x')),req,raw))
    def test_limits_preserve_existing_endpoint(self):
        self.assertEqual(self.proto.MAX_REQUEST,65536);self.assertEqual(self.proto.MAX_RESPONSE,16384)
    def test_wrong_response_kind_rejected_even_with_keeper_signature(self):
        d,_=self.partial();req=self.ext_request('status',d)
        v={'kind':'proposal','job_id':self.jid().hex(),'descriptor_hash':self.sc.sha(d).hex(),'stage_state':'RECEIVING','controller_revision':1,'proposal':self.st.proposal(d),'product_qualified':False}
        raw=self.proto.make_response(self.p,self.ks,self.hello(),req,True,v)
        self.err(None,lambda:self.proto.check_response(self.p,self.kp,self.hello(),req,raw))
    def test_dual_approval_does_not_authorize_wrong_connection_revision(self):
        d,_=self.partial();a=self.retire_request(d);hi=self.hello(revision=2)
        self.err(None,lambda:self.ext_request('retire',d,a,hi))
    def test_namespace_cannot_be_changed_without_resigning(self):
        raw=self.ext_request();b,o=self.sc.split(raw,self.sc.MAX_REQUEST);b[3]='status';o[0]=self.sc.dump(b,self.sc.MAX_REQUEST)
        self.err(None,lambda:self.ext_check(self.sc.dump(o,self.sc.MAX_REQUEST)))
    def test_oversize_and_truncated_requests_rejected(self):
        self.err(None,lambda:self.ext_check(b'x'*65537))
        raw=self.ext_request()
        for n in (0,1,len(raw)//2,len(raw)-1):
            with self.subTest(length=n):self.err(None,lambda:self.ext_check(raw[:n]))
    def test_response_same_count_other_job_rejected(self):
        d,_=self.partial();q=self.ext_request('status',d)
        v={'kind':'status','job_id':h('other').hex(),'descriptor_hash':self.sc.sha(d).hex(),'stage_state':'RECEIVING','controller_revision':1,'retirement':None,'product_qualified':False}
        raw=self.proto.make_response(self.p,self.ks,self.hello(),q,True,v)
        self.err(None,lambda:self.proto.check_response(self.p,self.kp,self.hello(),q,raw))
    def test_unsigned_proposal_file_not_a_signed_exchange(self):
        v=self.st.proposal(self.partial()[0]);raw=self.sc.json_bytes({'proposal':'untrusted'})
        self.err(None,lambda:self.sc.load(raw,65536))
    def test_terminal_view_cannot_claim_job_cancelled_or_record_gc(self):
        d,_=self.partial();v=self.st.retire(self.retire_request(d))
        for k in ('job_cancelled','records_reclaimed','secure_erase','physical_disk_quota','product_qualified'):
            bad=dict(v);bad[k]=True
            with self.subTest(field=k):self.err(None,lambda:self.proto.retirement_shape(bad))
    def test_pending_view_cannot_release_capacity(self):
        d,_=self.partial();v=self.st.retire(self.retire_request(d));v['state']='INTENT'
        self.err(None,lambda:self.proto.retirement_shape(v))
