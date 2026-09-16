from pathlib import Path
from unittest.mock import patch
from jobs_support import JobTest,h
from par_upload_window import contract as w
class JobLifecycle(JobTest):
    def test_retire_verifies_receipt_and_quota(self):
        cmd=self.retired_command();before=self.window.diagnostics()['reserved_bytes']
        self.jobs.submit(self.jid(),action='retire',command=cmd);r=self.complete(self.jid());self.assertTrue(r['result_verified']);self.assertGreater(before,0);self.assertEqual(self.window.diagnostics()['reserved_bytes'],0)
    def test_close_preserves_then_compact_reclaims(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.complete(self.jid());self.assertEqual(self.window.phase,'CLOSED');self.assertGreater(self.window.diagnostics()['records'],0)
        self.jobs.submit(self.jid('compact'),action='compact');self.complete(self.jid('compact'));self.assertEqual(self.window.phase,'CLEANED')
    def test_open_second_generation_once(self):
        receipt=self.finish();grant=self.grant_for(2,w.digest(receipt));self.jobs.submit(self.jid(),action='open',command=grant);self.complete(self.jid());self.jobs.step(self.jid());self.assertEqual(self.window.pin()[1],2)
    def test_close_then_later_generation_historical_result(self):
        self.jobs.submit(self.jid(),**self.close_args());self.complete(self.jid());first=self.jobs.result(self.jid());r=self.window.compact();self.next_window(r)
        self.assertEqual(self.jobs.result(self.jid()),first)
    def test_retire_result_after_record_compaction(self):
        cmd=self.retired_command();self.jobs.submit(self.jid(),action='retire',command=cmd);self.complete(self.jid());result=self.jobs.result(self.jid());self.finish();self.assertEqual(self.jobs.result(self.jid()),result)
    def test_duplicate_after_success_never_signs(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.complete(self.jid())
        with patch.object(self.p,'sign',side_effect=AssertionError('query signed')):
            self.assertEqual(self.jobs.submit(self.jid(),**a)['state'],'SUCCEEDED');self.jobs.poll(self.jid());self.jobs.result(self.jid())
    def test_cancel_idempotent_and_no_mutation(self):
        self.jobs.submit(self.jid(),**self.close_args());self.jobs.cancel(self.jid())
        with patch.object(self.p,'sign',side_effect=AssertionError('repeat cancel signed')):self.assertEqual(self.jobs.cancel(self.jid())['state'],'CANCELLED')
        self.assertEqual(self.window.phase,'OPEN')
    def test_activity_waits_at_safe_point(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.activity_count=1
        r=self.jobs.step(self.jid());self.assertEqual(r['state'],'PREPARED');self.assertEqual(r['waiting_reason'],'ACTIVE_TRANSFERS')
        self.activity_count=0;self.assertEqual(self.jobs.step(self.jid())['state'],'SUCCEEDED')
    def test_cancel_while_waiting_is_safe(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.activity_count=1;self.jobs.step(self.jid());self.jobs.cancel(self.jid());self.activity_count=0
        self.err('JOB_CANCELLED',lambda:self.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_stale_authority_before_validation(self):
        self.jobs.submit(self.jid(),**self.close_args());self.change_authority();self.err('STALE_AUTHORITY',lambda:self.jobs.step(self.jid()));self.assertTrue(self.jobs.poll(self.jid())['cancellable'])
    def test_stale_authority_after_preparation(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.change_authority();self.err('STALE_AUTHORITY',lambda:self.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_target_changed_after_preparation(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.prepare(self.jid());self.window.close_window(a['command'],a['archive']);self.err('JOB_TARGET_CHANGED',lambda:self.jobs.step(self.jid()))
    def test_activity_callback_mutates_authority_rechecked(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid())
        def activity():self.change_authority();return 0
        self.jobs.activity=activity;self.err('STALE_AUTHORITY',lambda:self.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_unknown_requires_reconcile_and_explicit_retry(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid())
        with patch.object(self.jobs.backend,'apply',side_effect=OSError('not dispatched')):self.assertEqual(self.jobs.step(self.jid())['state'],'OUTCOME_UNKNOWN')
        self.err('RECONCILE_REQUIRED',lambda:self.jobs.step(self.jid()));self.err('CANCEL_TOO_LATE',lambda:self.jobs.cancel(self.jid()))
        self.assertEqual(self.jobs.reconcile(self.jid())['state'],'RETRY_READY');self.err('EXPLICIT_RETRY_REQUIRED',lambda:self.jobs.step(self.jid()));self.assertEqual(self.jobs.retry(self.jid())['state'],'SUCCEEDED')
    def test_ack_loss_reconciles_without_redispatch(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid())
        def fault(event):
            if event=='job.effect.after_dispatch':raise OSError('lost reply')
        self.jobs.journal.observer=fault;self.assertEqual(self.jobs.step(self.jid())['state'],'OUTCOME_UNKNOWN');self.jobs.journal.observer=None
        with patch.object(self.jobs.backend,'apply',side_effect=AssertionError('duplicate effect')):self.assertEqual(self.jobs.reconcile(self.jid())['state'],'SUCCEEDED')
    def test_reopen_queued_does_not_execute(self):
        self.jobs.submit(self.jid(),**self.close_args());self.reopen_jobs();self.assertEqual(self.jobs.poll(self.jid())['state'],'QUEUED');self.assertEqual(self.window.phase,'OPEN')
    def test_reopen_cancelled_stays_cancelled(self):
        self.jobs.submit(self.jid(),**self.close_args());self.jobs.cancel(self.jid());self.reopen_jobs();self.err('JOB_CANCELLED',lambda:self.jobs.step(self.jid()))
    def test_reconcile_stale_pending_refuses_new_effect(self):
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid())
        with patch.object(self.jobs.backend,'apply',side_effect=OSError()):self.jobs.step(self.jid())
        self.change_authority();self.err('STALE_AUTHORITY',lambda:self.jobs.reconcile(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_historical_success_after_authority_change(self):
        self.jobs.submit(self.jid(),**self.close_args());self.complete(self.jid());self.change_authority();self.assertTrue(self.jobs.poll(self.jid())['result_verified'])
    def test_unfinished_upload_not_accepted_for_close(self):
        t=self.upload_stage(3);self.err('WINDOW_NOT_TERMINAL',self.window.export_archive);self.assertEqual(self.jobs.list(),[])
    def test_presenter_no_false_progress_or_rollback(self):
        from par_management_jobs import present
        self.jobs.submit(self.jid(),**self.close_args());s=present(self.jobs.poll(self.jid()));self.assertTrue(s['cancel_enabled']);self.assertFalse(s['determinate_progress']);self.assertFalse(s['cancel_is_rollback'])
    def test_result_before_verified_refused(self):
        self.jobs.submit(self.jid(),**self.close_args());self.err('RESULT_NOT_VERIFIED',lambda:self.jobs.result(self.jid()))
