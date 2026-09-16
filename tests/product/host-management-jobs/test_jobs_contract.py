from jobs_support import JobTest,h
class JobContract(JobTest):
    def test_submit_is_queued_without_gateway_effect(self):
        a=self.close_args();pin=self.window.pin();r=self.jobs.submit(self.jid(),**a)
        self.assertEqual(r['state'],'QUEUED');self.assertTrue(r['cancellable']);self.assertEqual(self.window.pin(),pin)
    def test_stable_id_duplicate(self):
        a=self.close_args();x=self.jobs.submit(self.jid(),**a);y=self.jobs.submit(self.jid(),**a);self.assertEqual(x,y)
    def test_different_input_same_id_rejected(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.err('JOB_CONFLICT',lambda:self.jobs.submit(self.jid(),action='compact'))
    def test_alias_job_same_signed_intent_rejected(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.err('JOB_ALIAS',lambda:self.jobs.submit(self.jid('two'),**a))
    def test_arbitrary_method_denied(self):self.err('JOB_METHOD',lambda:self.jobs.submit(self.jid(),action='execute_shell'))
    def test_job_id_requires_bytes(self):self.err('JOB_SCHEMA',lambda:self.jobs.submit('x'*32,action='compact'))
    def test_empty_command_rejected(self):self.err('JOB_SCHEMA',lambda:self.jobs.submit(self.jid(),action='close',command=b''))
    def test_compact_rejects_command(self):self.err('JOB_SCHEMA',lambda:self.jobs.submit(self.jid(),action='compact',command=b'x'))
    def test_bad_signature_not_enqueued(self):
        a=self.close_args();a['command']=a['command'][:-1]+bytes([a['command'][-1]^1]);self.err(None,lambda:self.jobs.submit(self.jid(),**a));self.assertEqual(self.jobs.list(),[])
    def test_cancel_then_step_does_not_dispatch(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.jobs.cancel(self.jid());self.err('JOB_CANCELLED',lambda:self.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_cancel_prepared(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.prepare(self.jid());self.assertTrue(self.jobs.poll(self.jid())['cancellable']);self.jobs.cancel(self.jid());self.assertEqual(self.window.phase,'OPEN')
    def test_success_not_cancellable(self):
        self.jobs.submit(self.jid(),**self.close_args());self.complete(self.jid());self.err('CANCEL_TOO_LATE',lambda:self.jobs.cancel(self.jid()))
    def test_poll_redacted(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);s=self.jobs.poll(self.jid());self.assertNotIn(a['command'].hex(),str(s));self.assertNotIn('archive',s);self.assertFalse(s['product_qualified']);self.assertFalse(s['result_verified'])
    def test_activity_observer_required(self):
        self.jobs.close();self.jobs=self.m.ManagementJobs(self.window,self.jroot);self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.err('ACTIVITY_OBSERVER_REQUIRED',lambda:self.jobs.step(self.jid()))
    def test_invalid_activity_type(self):
        self.jobs.activity=lambda:True;self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.err('JOB_ACTIVITY',lambda:self.jobs.step(self.jid()))
    def test_queue_budget(self):
        self.jobs.close();self.jroot=self.jroot.with_name('small-jobs');self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0,max_jobs=1)
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.err('JOB_CAPACITY',lambda:self.jobs.submit(self.jid('two'),action='compact'))
    def test_root_cannot_alias_gateway(self):self.err('JOB_PATH_SCOPE',lambda:self.m.ManagementJobs(self.window,self.wroot,activity=lambda:0))
    def test_same_root_writer_refused(self):self.err('WRITER_BUSY',lambda:self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0))
