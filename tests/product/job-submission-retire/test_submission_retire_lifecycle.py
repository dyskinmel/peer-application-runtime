from submission_retire_support import RetireTest,h,patch
class RetirementLifecycle(RetireTest):
    def test_partial_retirement_frees_only_payload_reservation(self):
        d,r=self.partial();q=self.retire_request(d);before=self.keeper.diagnostics();v=self.st.retire(q)
        self.assertEqual(v['state'],'TOMBSTONED');self.assertEqual(v['reservation_released_bytes'],len(r))
        self.assertEqual(v['removed_payload_bytes'],17);self.assertFalse(self.st.payload_path(self.jid()).exists())
        self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],0);self.assertEqual(self.st.diagnostics()['records'],1)
        self.assertEqual(self.keeper.diagnostics(),before);self.assertEqual(self.host.jobs.list(),[])
    def test_empty_begun_request(self):
        d=self.descriptor();self.st.begin(d);v=self.st.retire(self.retire_request(d));self.assertEqual(v['removed_payload_bytes'],0)
    def test_ready_retirement_does_not_register(self):
        d,r=self.ready();self.st.retire(self.retire_request(d));self.assertEqual(self.host.jobs.list(),[])
    def test_registered_job_survives_and_can_execute(self):
        d,r=self.ready();self.st.submit(d);before=self.host.jobs.journal.path(self.jid()).read_bytes()
        self.st.retire(self.retire_request(d));self.assertEqual(self.host.jobs.journal.path(self.jid()).read_bytes(),before)
        self.host.schedule(self.jid());self.complete();self.reopen();self.assertEqual(self.st.retirement_status(self.jid())['state'],'TOMBSTONED')
    def test_repeated_request_not_double_release_or_sign(self):
        d,r=self.partial();q=self.retire_request(d);v=self.st.retire(q)
        with patch.object(self.p,'sign',side_effect=AssertionError('resigning')):
            self.assertEqual(self.st.retire(q),v);self.reopen();self.assertEqual(self.st.retire(q),v)
    def test_every_original_entry_refuses_tombstone(self):
        d,r=self.ready();self.st.retire(self.retire_request(d))
        for name in ('begin','progress','submit','reconcile','retry'):
            self.err('SUBMIT_RETIRED',lambda n=name:getattr(self.st,n)(d))
        self.err('SUBMIT_RETIRED',lambda:self.st.chunk(d,0,r[:1]))
    def test_inflight_requires_separate_reconcile(self):
        d,r=self.ready();self.stop_at('submit.before_dispatch',lambda:self.st.submit(d));q=self.retire_request(d)
        self.err('RETIRE_RECONCILE_REQUIRED',lambda:self.st.retire(q))
        with patch.object(self.host.jobs,'submit',side_effect=AssertionError('auto registration')):
            self.assertEqual(self.st.reconcile_registration(q)['state'],'RETRY_READY')
            self.err('RETIRE_TARGET',lambda:self.st.retire(q))
            self.st.retire(self.retire_request(d))
    def test_lost_registration_response_preserves_job(self):
        d,r=self.ready();self.stop_at('submit.after_dispatch',lambda:self.st.submit(d));q=self.retire_request(d)
        self.assertEqual(self.st.reconcile_registration(q)['state'],'REGISTERED');self.st.retire(self.retire_request(d))
        self.assertEqual(len(self.host.jobs.list()),1);self.assertIsNone(self.host.selected)
    def test_reconcile_after_controller_rotation(self):
        d,r=self.ready();self.stop_at('submit.before_dispatch',lambda:self.st.submit(d));new=h('new-op');self.ctl.replace_controller(self.p.sign_public(new),2)
        q=self.retire_request(d,operator=new);self.assertEqual(self.st.reconcile_registration(q)['state'],'RETRY_READY')
        self.st.retire(self.retire_request(d,operator=new));self.assertEqual(self.host.jobs.list(),[])
    def test_capacity_reusable_records_retained(self):
        self.reopen();self.st.close();cfg=self.sroot/'CONFIG.cbor';v=self.sc.load(cfg.read_bytes(),4096);v[5]=1024;cfg.write_bytes(self.sc.dump(v,4096));self.st=None
        self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,max_bytes=1024)
        r=b'x'*900;d=self.descriptor(r);self.st.begin(d);self.st.chunk(d,0,r[:17]);d2=self.descriptor(r,h('other'))
        self.err('SUBMIT_CAPACITY',lambda:self.st.begin(d2));self.st.retire(self.retire_request(d));self.assertEqual(self.st.begin(d2)['state'],'RECEIVING')
    def test_pending_retirement_stops_new_chunks(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen()
        self.err('SUBMIT_RETIRED',lambda:self.st.chunk(d,17,r[17:]));self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],len(r));self.st.retire(q)
    def test_rebind_exact_target_after_rotation(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen()
        new=h('second-op');self.ctl.replace_controller(self.p.sign_public(new),2);self.err('STALE_CONTROLLER',lambda:self.st.retire(q))
        q2=self.retire_request(d,operator=new);v=self.st.rebind(q2);self.assertEqual(v['state'],'INTENT');self.assertTrue(self.st.payload_path(self.jid()).exists());self.st.retire(q2)
    def test_restart_never_deletes_pending_payload(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen()
        self.assertTrue(self.st.payload_path(self.jid()).exists());self.assertEqual(self.st.retirement_status(self.jid())['state'],'INTENT')
