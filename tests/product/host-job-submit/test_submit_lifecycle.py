from submit_support import SubmitTest,h
class SubmitLifecycle(SubmitTest):
    def test_registration_not_selection_or_execution(self):
        d,r=self.ready();v=self.st.submit(d);self.assertEqual(v['state'],'REGISTERED');self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED');self.assertIsNone(self.host.selected);self.assertEqual(self.window.phase,'OPEN')
    def test_duplicate_no_second_job(self):
        d,r=self.ready();v=self.st.submit(d);self.assertEqual(self.st.submit(d),v);self.assertEqual(len(self.host.jobs.list()),1)
    def test_select_is_separate(self):
        d,r=self.ready();self.st.submit(d);self.host.schedule(self.jid());self.complete();self.assertEqual(self.window.phase,'CLOSED')
    def test_retry_registered_after_execution(self):
        d,r=self.ready();self.st.submit(d);self.host.schedule(self.jid());self.complete();self.assertEqual(self.st.submit(d)['state'],'REGISTERED');self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
    def test_duplicate_cancelled_registration_not_reactivated(self):
        d,r=self.ready();self.st.submit(d);self.host.cancel(self.jid());self.st.submit(d);self.assertEqual(self.host.jobs.poll(self.jid())['state'],'CANCELLED');self.assertIsNone(self.host.selected)
    def test_submit_incomplete(self):
        d=self.descriptor();self.st.begin(d);self.err('SUBMIT_INCOMPLETE',lambda:self.st.submit(d));self.assertEqual(self.host.jobs.list(),[])
    def test_signature_in_payload_not_replaced_by_controller(self):
        a,q=self.proposed();q=bytearray(q);q[-1]^=1;d,_=self.ready(self.sc.pack_job('close',bytes(q),a));self.err(None,lambda:self.st.submit(d));self.assertEqual(self.host.jobs.list(),[])
    def test_stale_target_before_begin(self):
        d=self.descriptor(target=h('old'));self.err('SUBMIT_TARGET_CHANGED',lambda:self.st.begin(d));self.assertEqual(self.st.diagnostics()['records'],0)
    def test_target_changes_before_submit(self):
        d,_=self.ready();self.finish();self.err('SUBMIT_TARGET_CHANGED',lambda:self.st.submit(d));self.assertEqual(self.host.jobs.list(),[])
    def test_same_intent_other_job_id(self):
        d,r=self.ready();self.st.submit(d);d2,_=self.ready(r,h('alias'));self.err('JOB_ALIAS',lambda:self.st.submit(d2));self.assertEqual(len(self.host.jobs.list()),1)
    def test_exact_preexisting_job_registration(self):
        d,r=self.ready()
        a,q=self.proposed();self.host.submit(self.jid(),action='close',command=q,archive=a)
        # Context is identical; an exact pre-existing registration is reconciled, not resubmitted.
        self.assertEqual(self.st.submit(d)['state'],'REGISTERED');self.assertEqual(len(self.host.jobs.list()),1)
    def test_after_job_effect_exception_unknown_then_reconcile(self):
        d,_=self.ready()
        def fail(n):
            if n=='submit.after_dispatch':raise RuntimeError('lost acknowledgement')
        self.st.observer=fail;self.err('SUBMIT_OUTCOME_UNKNOWN',lambda:self.st.submit(d));self.st.observer=None
        self.assertEqual(self.st.progress(d)['state'],'INFLIGHT');self.assertEqual(len(self.host.jobs.list()),1)
        self.assertEqual(self.st.reconcile(d)['state'],'REGISTERED');self.assertIsNone(self.host.selected)
    def test_before_dispatch_exception_requires_explicit_retry(self):
        d,_=self.ready()
        def fail(n):
            if n=='submit.before_dispatch':raise RuntimeError('stopped')
        self.st.observer=fail;self.err('SUBMIT_OUTCOME_UNKNOWN',lambda:self.st.submit(d));self.st.observer=None
        self.err('SUBMIT_RECONCILE_REQUIRED',lambda:self.st.submit(d));self.assertEqual(self.host.jobs.list(),[])
        self.assertEqual(self.st.reconcile(d)['state'],'RETRY_READY');self.err('SUBMIT_EXPLICIT_RETRY',lambda:self.st.submit(d));self.assertEqual(self.st.retry(d)['state'],'REGISTERED')
    def test_reconcile_ready_refused(self):
        d,_=self.ready();self.err('SUBMIT_NOT_RECONCILABLE',lambda:self.st.reconcile(d))
    def test_retry_ready_refused(self):
        d,_=self.ready();self.err('SUBMIT_EXPLICIT_RETRY',lambda:self.st.retry(d))
    def test_missing_registered_job_refused(self):
        d,_=self.ready();self.st.submit(d);self.host.jobs.journal.path(self.jid()).unlink();self.err(None,lambda:self.st.progress(d))
    def test_reopen_registered_does_not_dispatch(self):
        d,_=self.ready();self.st.submit(d);self.reopen();self.assertEqual(self.st.progress(d)['state'],'REGISTERED');self.assertIsNone(self.host.selected)
    def test_target_changes_at_dispatch_boundary(self):
        d,_=self.ready()
        def change(n):
            if n=='submit.before_dispatch':self.finish()
        self.st.observer=change;self.err('SUBMIT_OUTCOME_UNKNOWN',lambda:self.st.submit(d));self.st.observer=None;self.assertEqual(self.host.jobs.list(),[]);self.assertEqual(self.st.progress(d)['state'],'INFLIGHT')
    def test_registered_job_journal_capacity_not_bypassed(self):
        # Reject before INFLIGHT by using a constrained separate job journal.
        from par_management_jobs import ManagementJobs
        self.host.jobs.close();self.host.jobs=ManagementJobs(self.window,self.jroot.with_name('one-job'),max_jobs=1,activity=lambda:0);self.st.jobs=self.host.jobs
        self.host.submit(h('already-registered'),action='close',command=self.proposed()[1],archive=self.proposed()[0])
        self.err('JOB_CAPACITY',lambda:self.st.begin(self.descriptor()));self.assertEqual(self.st.diagnostics()['records'],0)
