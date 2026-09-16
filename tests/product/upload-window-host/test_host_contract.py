import hashlib
from host_support import HostTest,h,pr
class HostContract(HostTest):
    def test_hello_roundtrip_binds_store_and_generation(self):
        b=self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,self.hello());self.assertEqual(b[8],self.store_id);self.assertEqual(b[9],self.w.digest(self.grant));self.assertEqual(b[10],1)
    def test_wrong_keeper(self):self.err(None,lambda:self.hp.check_hello(self.p,h('other'),self.store_id,self.grant,self.hello()))
    def test_wrong_store(self):self.err(None,lambda:self.hp.check_hello(self.p,self.kp,h('other'),self.grant,self.hello()))
    def test_wrong_generation(self):self.err(None,lambda:self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,self.hello(window=self.grant_for(2,h('prior')))))
    def test_explicit_closed_hello(self):
        b=self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,self.hello(phase='CLOSED'));self.assertEqual(b[11],'CLOSED')
    def test_closed_hello_cannot_start_request(self):self.err('WINDOW_CLOSED',lambda:self.host_request(self.hello(phase='CLOSED')))
    def test_cleaned_hello_cannot_start_request(self):self.err('WINDOW_CLOSED',lambda:self.host_request(self.hello(phase='CLEANED')))
    def test_legacy_hello_rejected(self):
        raw=pr.make_hello(self.p,self.ks,h('boot'),h('challenge'),1000)
        self.err(None,lambda:self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,raw))
    def test_raw_upload_command_rejected(self):self.err(None,lambda:self.host_request(command=self.cmd('progress',h('token'))))
    def test_request_roundtrip(self):
        raw=self.command();hello=self.hello();req=self.host_request(hello,raw)
        self.assertEqual(self.hp.check_request(self.p,self.kp,self.store_id,self.grant,hello,req),raw)
    def test_challenge_replay_rejected(self):
        self.err(None,lambda:self.hp.check_request(self.p,self.kp,self.store_id,self.grant,self.hello(challenge=h('new')),self.host_request()))
    def test_wrong_subject_cannot_sign(self):self.err(None,lambda:self.hp.make_request(self.p,h('wrong'),self.hello(),self.grant,self.command()))
    def test_admin_retire_denied(self):
        self.upload_stage(1);raw=self.wrap(self.retirement_request(),'retire')
        self.err('METHOD_DENIED',lambda:self.host_request(command=raw))
    def test_admin_rebind_denied(self):
        self.upload_stage(1);raw=self.wrap(self.retirement_request(),'rebind')
        self.err('METHOD_DENIED',lambda:self.host_request(command=raw))
    def test_window_open_grant_not_a_data_command(self):self.err(None,lambda:self.host_request(command=self.grant))
    def test_corrupt_request_signature(self):
        req=self.host_request();o=pr.load(req,65536);o[1]=bytes(64)
        self.err(None,lambda:self.hp.check_request(self.p,self.kp,self.store_id,self.grant,self.hello(),pr.dump(o,65536)))
    def test_response_roundtrip(self):
        hello=self.hello();request=self.host_request(hello);r=self.hp.make_response(self.p,self.ks,hello,request,True,h('ok'))
        self.assertEqual(self.hp.check_response(self.p,self.kp,hello,request,r),h('ok'))
    def test_response_request_binding(self):
        hello=self.hello();q=self.host_request(hello);r=self.hp.make_response(self.p,self.ks,hello,q,True,h('ok'))
        self.err(None,lambda:self.hp.check_response(self.p,self.kp,hello,self.host_request(hello),r))
    def test_response_challenge_binding(self):
        hello=self.hello();q=self.host_request(hello);r=self.hp.make_response(self.p,self.ks,hello,q,True,h('ok'))
        self.err(None,lambda:self.hp.check_response(self.p,self.kp,self.hello(challenge=h('new')),q,r))
    def test_no_arbitrary_remote_error(self):self.err(None,lambda:self.hp.make_response(self.p,self.ks,self.hello(),self.host_request(),False,'/secret/path'))
    def test_explicit_remote_window_closed(self):
        hello=self.hello();req=self.host_request(hello);r=self.hp.make_response(self.p,self.ks,hello,req,False,'STALE_WINDOW')
        self.err('REMOTE_STALE_WINDOW',lambda:self.hp.check_response(self.p,self.kp,hello,req,r))
    def test_boolean_version_rejected_even_signed(self):
        b,o=self.hp._split(self.hello(),4096);b[0]=True;raw=self.hp._signed(self.p,self.ks,'hello',b,4096)
        self.err(None,lambda:self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,raw))
    def test_boolean_sequence_rejected_even_signed(self):
        b,o=self.hp._split(self.hello(),4096);b[10]=True;raw=self.hp._signed(self.p,self.ks,'hello',b,4096)
        self.err(None,lambda:self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,raw))
    def test_unknown_hello_field_rejected(self):
        b,o=self.hp._split(self.hello(),4096);b[99]=0;raw=self.hp._signed(self.p,self.ks,'hello',b,4096)
        self.err(None,lambda:self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,raw))
    def test_unknown_phase_rejected(self):self.err(None,lambda:self.hello(phase='READY'))
    def test_zero_challenge_length_rejected(self):self.err(None,lambda:self.hello(challenge=b''))
    def test_request_cannot_exceed_fixed_limit(self):
        self.err(None,lambda:self.hp.check_request(self.p,self.kp,self.store_id,self.grant,self.hello(),b'\0'*65537))
    def test_profile_distinct_from_legacy(self):self.assertNotEqual(self.hp.PROFILE,pr.PROFILE)
