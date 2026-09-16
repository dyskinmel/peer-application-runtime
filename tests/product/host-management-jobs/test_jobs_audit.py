import os,threading
from pathlib import Path
from unittest.mock import patch
from jobs_support import JobTest,h
from par_management_jobs import contract as c
class JobAudit(JobTest):
    def submit(self):return self.jobs.submit(self.jid(),**self.close_args())
    def mutate_signed(self,fn):
        b,a,raw=self.jobs.journal.read(self.jid());fn(b);path=self.jobs.journal.path(self.jid());self.jobs.close();path.write_bytes(c.pack(self.p,self.ks,b,a))
    def test_bad_signature_on_reopen(self):
        self.submit();path=self.jobs.journal.path(self.jid());raw=path.read_bytes();self.jobs.close();path.write_bytes(raw[:20]+bytes([raw[20]^1])+raw[21:]);self.err(None,self.reopen_jobs_new)
    def test_archive_hash_checked(self):
        self.submit();path=self.jobs.journal.path(self.jid());raw=path.read_bytes();self.jobs.close();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]));self.err('JOB_SCHEMA',self.reopen_jobs_new)
    def test_same_session_journal_rollback_detected(self):
        self.submit();path=self.jobs.journal.path(self.jid());old=path.read_bytes();self.jobs.step(self.jid());path.write_bytes(old);self.err('JOB_JOURNAL_CHANGED',lambda:self.jobs.poll(self.jid()))
    def test_queued_cancel_reopen_does_not_sign(self):
        self.submit();self.jobs.cancel(self.jid());self.jobs.close()
        with patch.object(self.p,'sign',side_effect=AssertionError('restart signed')):self.reopen_jobs_new();self.jobs.poll(self.jid())
    def test_journal_result_must_match_underlying_state(self):
        self.submit();self.complete(self.jid());self.mutate_signed(lambda b:b[13][-1].update({2:b'fake'}));self.reopen_jobs_new();self.err('JOB_RESULT_MISMATCH',lambda:self.jobs.poll(self.jid()))
    def test_missing_backend_archive_refuses_historical_success(self):
        self.submit();self.complete(self.jid());next(self.window.archives.iterdir()).unlink();self.err('ARCHIVE_MISSING',lambda:self.jobs.poll(self.jid()))
    def test_wider_permissions_refused(self):
        self.submit();self.jobs.journal.path(self.jid()).chmod(0o644);self.err(None,lambda:self.jobs.poll(self.jid()))
    def test_symlink_refused(self):
        self.submit();path=self.jobs.journal.path(self.jid());raw=path.read_bytes();path.unlink();target=Path(self.tmp.name)/'foreign';target.write_bytes(raw);target.chmod(0o600);path.symlink_to(target);self.err(None,lambda:self.jobs.poll(self.jid()))
    def test_owner_thread_cannot_cancel(self):
        self.submit();errors=[]
        def call():
            try:self.jobs.cancel(self.jid())
            except Exception as e:errors.append(e.code)
        t=threading.Thread(target=call);t.start();t.join();self.assertEqual(errors,['OWNER_REQUIRED']);self.assertEqual(self.jobs.poll(self.jid())['state'],'QUEUED')
    def test_reentrant_cancel_rejected_before_dispatch(self):
        self.submit();self.prepare(self.jid());errors=[]
        def observer(e):
            if e=='job.effect.before_dispatch':
                try:self.jobs.cancel(self.jid())
                except Exception as x:errors.append(x.code)
        self.jobs.journal.observer=observer;self.jobs.step(self.jid());self.assertEqual(errors,['OWNER_REQUIRED'])
    def test_signed_true_revision_rejected(self):
        self.submit();b,a,raw=self.jobs.journal.read(self.jid());b[13][0][0]=False;self.err('JOB_SCHEMA',lambda:c.pack(self.p,self.ks,b,a))
    def test_signed_skipped_transition_rejected(self):
        self.submit();b,a,raw=self.jobs.journal.read(self.jid());b[13][0][1]='SUCCEEDED';self.err('JOB_TRANSITION',lambda:c.pack(self.p,self.ks,b,a))
    def test_public_poll_does_not_expose_plaintext_or_approvals(self):
        self.submit();s=self.jobs.poll(self.jid());allowed={'job_id','action','state','journal_state','revision','input_digest','target_sequence','cancellable','may_have_effect','requires_reconciliation','explicit_retry_required','result_verified','result_digest','waiting_reason','progress_total','product_qualified'}
        self.assertEqual(set(s),allowed)
    def test_job_file_magic_and_size_checked(self):
        self.submit();path=self.jobs.journal.path(self.jid());self.jobs.close();path.write_bytes(b'not a journal');self.err('JOB_SCHEMA',self.reopen_jobs_new)
    def test_pin_detects_missing_job_after_restart(self):
        self.submit();pin=self.jobs.pin();self.jobs.close();self.jobs.journal.path(self.jid()).unlink();self.err('JOB_PIN',lambda:self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0,expected_pin=pin))
    def test_pin_accepts_later_valid_history(self):
        self.submit();pin=self.jobs.pin();self.jobs.step(self.jid());self.jobs.close();self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0,expected_pin=pin);self.assertEqual(self.jobs.poll(self.jid())['state'],'VALIDATED')
    def test_pin_rejects_old_cancelled_history(self):
        self.submit();path=self.jobs.journal.path(self.jid());old=path.read_bytes();self.jobs.cancel(self.jid());pin=self.jobs.pin();self.jobs.close();path.write_bytes(old);self.err('JOB_PIN',lambda:self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0,expected_pin=pin))
    def test_missing_known_job_blocks_list(self):
        self.submit();self.jobs.journal.path(self.jid()).unlink();self.err('JOB_JOURNAL_CHANGED',self.jobs.list)
    def test_foreign_file_blocks_step(self):
        self.submit();p=self.jroot/'unexpected';p.write_bytes(b'x');p.chmod(0o600);self.err('JOB_LAYOUT',lambda:self.jobs.step(self.jid()))
    def test_dead_process_job_cannot_be_cancelled(self):
        self.submit();self.prepare(self.jid());b,a=self.jobs._read(self.jid());self.jobs.journal.transition(b,a,'EXECUTING');self.reopen_jobs();self.err('CANCEL_TOO_LATE',lambda:self.jobs.cancel(self.jid()));self.assertEqual(self.jobs.poll(self.jid())['state'],'OUTCOME_UNKNOWN')
    def test_history_budget_reserved_before_effect(self):
        self.submit();self.prepare(self.jid())
        for _ in range(9):
            b,a=self.jobs._read(self.jid());b=self.jobs.journal.transition(b,a,'EXECUTING');b=self.jobs.journal.transition(b,a,'OUTCOME_UNKNOWN');self.jobs.journal.transition(b,a,'RETRY_READY')
        with patch.object(self.jobs.backend,'apply',side_effect=AssertionError('effect without journal space')):self.err('JOB_HISTORY_LIMIT',lambda:self.jobs.retry(self.jid()))
        self.assertEqual(self.window.phase,'OPEN')
    def test_config_bool_cannot_alias_integer_version(self):
        p=self.jroot/'CONFIG.cbor';value=c.load(p.read_bytes());value[0]=True;p.write_bytes(c.dump(value));self.err('JOB_SETTINGS',self.jobs.list)
    def test_pin_scope_mismatch(self):
        self.submit();pin=self.jobs.pin();pin[2]=h('foreign-scope');self.err('JOB_PIN',lambda:self.jobs.verify_pin(pin))
    def test_pin_duplicate_job_rejected(self):
        self.submit();pin=self.jobs.pin();pin[3].append(pin[3][0]);self.err('JOB_PIN',lambda:self.jobs.verify_pin(pin))
    def test_cancel_file_result_lost_does_not_release_authorization(self):
        a=self.close_args();self.jobs.submit(self.jid(),**a);self.jobs.cancel(self.jid());self.assertEqual(self.window.phase,'OPEN')
        # Cancellation stops this job, not another explicitly authorized actor.
        self.window.close_window(a['command'],a['archive']);self.assertEqual(self.jobs.poll(self.jid())['state'],'CANCELLED')
    def test_provider_replacement_blocks_execution(self):
        self.submit();self.prepare(self.jid());previous=self.window.provider
        try:self.window.provider=object();self.err('JOB_PROVIDER_CHANGED',lambda:self.jobs.step(self.jid()))
        finally:self.window.provider=previous
    def test_job_copy_from_other_id_rejected(self):
        self.submit();p=self.jobs.journal.path(self.jid());raw=p.read_bytes();other=self.jobs.journal.path(self.jid('two'));other.write_bytes(raw);other.chmod(0o600);self.err('JOB_SCOPE',self.jobs.list)
