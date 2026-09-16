from submission_retire_support import RetireTest,h
class RetirementContract(RetireTest):
    def test_both_signatures_required(self):
        d,r=self.partial();raw=self.retire_request(d);b,o=self.rc.split_request(raw)
        for k in (1,2):
            altered=dict(o);altered[k]=bytes(64)
            self.err('RETIRE_SIGNATURE',lambda:self.st.retire(self.rc.dump(altered)))
        self.assertEqual(self.st.progress(d)['received'],17)
    def test_wrong_original_signer(self):
        d,r=self.partial();q=self.retire_request(d,origin=h('wrong-origin'))
        self.err('RETIRE_ORIGIN',lambda:self.st.retire(q));self.assertTrue(self.st.payload_path(self.jid()).exists())
    def test_wrong_current_signer(self):
        d,r=self.partial();q=self.retire_request(d,operator=h('wrong-current'))
        self.err('STALE_CONTROLLER',lambda:self.st.retire(q))
    def test_old_revision_refused(self):
        d,r=self.partial();q=self.retire_request(d);self.ctl.replace_controller(self.op,2)
        self.err('STALE_CONTROLLER',lambda:self.st.retire(q))
    def test_request_cannot_change_descriptor(self):
        d,r=self.partial();prop=self.st.proposal(d);prop['descriptor_hash']=h('other')
        q=self.rc.make_request(self.p,self.os,self.os,revision=1,nonce=h('n'),**prop)
        self.err('RETIRE_TARGET',lambda:self.st.retire(q))
    def test_request_cannot_change_stage(self):
        d,r=self.partial();q=self.retire_request(d);self.st.chunk(d,17,r[17:])
        self.err('RETIRE_TARGET',lambda:self.st.retire(q))
    def test_true_not_integer_revision(self):
        d,r=self.partial();prop=self.st.proposal(d)
        self.err(None,lambda:self.rc.make_request(self.p,self.os,self.os,revision=True,nonce=h('n'),**prop))
    def test_old_host_refuses_version_two(self):
        self.st.close();self.st=None
        self.err('SUBMIT_SETTINGS',lambda:self.sm.Submissions(self.ctl,self.sroot))
    def test_legacy_requires_explicit_migration(self):
        self.st.close();p=self.sroot/'CONFIG.cbor';old=dict(self.st.config);old[0]=1;old[1]=self.sc.PROFILE;p.write_bytes(self.sc.dump(old,4096));self.st=None
        self.err('RETIRE_MIGRATION_REQUIRED',lambda:self.rm.RetiringSubmissions(self.ctl,self.sroot))
        self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,migrate_legacy=True)
    def test_nonbytes_request(self):
        self.err(None,lambda:self.st.retire({}))
