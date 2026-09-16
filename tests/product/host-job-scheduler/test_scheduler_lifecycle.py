from unittest.mock import patch
from scheduler_support import SchedulerTest,h
from par_upload_window import contract as w
from par_verified_host import VerificationProvider
class SchedulerLifecycle(SchedulerTest):
    def test_close_compact_open_keep_both_endpoints_alive(self):
        self.terminal();old=self.beginwrapped;self.start_host();self.submit_close();self.host.schedule(self.jid());self.complete();self.assertEqual(self.window.phase,'CLOSED')
        jid=self.jid('compact');self.host.submit(jid,action='compact');self.host.schedule(jid)
        self.tick(3);self.assertEqual(self.host.jobs.poll(jid)['state'],'SUCCEEDED');receipt=self.host.jobs.result(jid)
        grant=self.grant_for(2,w.digest(receipt));jid=self.jid('open');self.host.submit(jid,action='open',command=grant);self.host.schedule(jid);self.tick(3)
        self.assertEqual(self.host.jobs.poll(jid)['state'],'SUCCEEDED');self.assertEqual(self.window.phase,'OPEN');self.err('WINDOW_SCOPE',lambda:self.window.execute(old));self.grant=grant
        s,hello=self.connect(True);self.assertEqual(self.hp.check_hello(self.p,self.kp,self.store_id,grant,hello)[11],'OPEN')
    def test_authority_change_before_effect_is_rejected(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2);self.change_authority();self.err('STALE_AUTHORITY',self.tick)
        self.assertEqual(self.window.phase,'OPEN');self.assertEqual(self.host.diagnostics()['mode'],'REVIEW_REQUIRED')
    def test_competing_close_is_not_overwritten(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2);archive,cmd=self.proposed();self.window.close_window(cmd,archive)
        self.err('JOB_TARGET_CHANGED',self.tick);self.assertFalse(self.host.upload.accepting)
    def test_unknown_does_not_auto_reconcile_or_retry(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2)
        def fail(e):
            if e=='job.effect.before_dispatch':raise OSError('synthetic')
        self.host.jobs.journal.observer=fail;self.tick();self.host.jobs.journal.observer=None
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'OUTCOME_UNKNOWN');self.tick(4);self.assertEqual(self.window.phase,'OPEN');self.assertFalse(self.host.upload.accepting)
        self.assertEqual(self.host.reconcile(self.jid())['state'],'RETRY_READY');self.tick(2);self.assertEqual(self.window.phase,'OPEN')
        self.host.arm_retry(self.jid());self.tick();self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
    def test_unknown_after_effect_reconciles_without_reexecution(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2)
        def fail(e):
            if e=='job.effect.after_dispatch':raise OSError('lost response')
        self.host.jobs.journal.observer=fail;self.tick();self.host.jobs.journal.observer=None
        self.assertEqual(self.window.phase,'CLOSED')
        with patch.object(self.host.jobs.backend,'apply',side_effect=AssertionError('must not execute')):
            self.assertEqual(self.host.reconcile(self.jid())['state'],'SUCCEEDED')
        self.assertTrue(self.host.read.accepting)
    def test_cancel_after_effect_not_rollback(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.complete();self.err('CANCEL_TOO_LATE',lambda:self.host.cancel(self.jid()));self.assertEqual(self.window.phase,'CLOSED')
    def test_cache_is_invalidated_at_effect_and_changed_scope(self):
        cache=VerificationProvider(self.p,mode='signatures');self.addCleanup(cache.close)
        self.keeper.provider=cache;self.window.provider=cache;self.window._inner.provider=cache
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2);before=cache.statistics()['invalidations'];self.tick()
        self.assertGreater(cache.statistics()['invalidations'],before);self.assertEqual(self.window.phase,'CLOSED')
    def test_reentrant_tick_from_effect_refused(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());seen=[]
        def reenter(e):
            if e=='job.effect.before_dispatch':
                try:self.host.tick(0)
                except Exception as ex:seen.append(ex.code)
        self.host.jobs.journal.observer=reenter;self.complete();self.assertEqual(seen,['SCHEDULER_REENTRY'])
    def test_reentrant_cancel_from_effect_refused(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());seen=[]
        def reenter(e):
            if e=='job.effect.before_dispatch':
                try:self.host.cancel(self.jid())
                except Exception as ex:seen.append(ex.code)
        self.host.jobs.journal.observer=reenter;self.complete();self.assertEqual(seen,['SCHEDULER_REENTRY'])
    def test_journal_failure_leaves_admission_paused(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2)
        def fail(e):
            if e=='job.succeeded.before_replace':raise OSError('journal failed')
        self.host.jobs.journal.observer=fail;self.err('JOB_JOURNAL_UNCERTAIN',self.tick);self.assertFalse(self.host.read.accepting);self.assertEqual(self.window.phase,'CLOSED')
    def test_presenter_has_no_fake_percentage_or_preemption(self):
        self.start_host();from par_job_scheduler.presenter import present
        r=present(self.host.diagnostics());self.assertFalse(r['determinate_progress']);self.assertFalse(r['forced_cancellation_supported']);self.assertTrue(r['management_is_synchronous'])
    def test_old_data_profile_and_limits_unchanged(self):
        from par_keeper_service.protocol import MAX_REQUEST as rlimit
        from par_window_host.protocol import MAX_REQUEST as wlimit
        self.assertEqual((rlimit,wlimit),(65536,65536))
    def test_invalid_reconcile_has_no_admission_side_effect(self):
        self.start_host();self.submit_close();self.err('NOT_RECONCILABLE',lambda:self.host.reconcile(self.jid()))
        self.assertTrue(self.host.read.accepting);self.assertTrue(self.host.upload.accepting)
    def test_resume_after_provider_swap_is_refused(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());saved=self.keeper.provider;self.keeper.provider=object()
        try:self.err('PROVIDER_CHANGED',lambda:self.host.cancel(self.jid()));self.assertFalse(self.host.read.accepting)
        finally:self.keeper.provider=saved
