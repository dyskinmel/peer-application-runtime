import json,os
from control_support import ControlTest,h
class ControlLifecycle(ControlTest):
    def test_status_is_readonly(self):
        before=list(self.cr.glob('*.op'));r=self.call('status')
        self.assertEqual(r['job']['state'],'QUEUED');self.assertEqual(r['outcome'],'STATUS');self.assertEqual(list(self.cr.glob('*.op')),before)
    def test_host_status_without_job(self):self.assertIsNone(self.call('status',jid=None)['job'])
    def test_select_is_ack_not_completion(self):
        r=self.call();self.assertEqual(r['outcome'],'ACCEPTED');self.assertEqual(r['job']['state'],'QUEUED');self.assertEqual(r['host']['mode'],'DRAINING')
    def test_cancel_before_dispatch(self):
        self.call();r=self.call('cancel');self.assertEqual(r['job']['state'],'CANCELLED');self.assertEqual(self.host.gateway.phase,'OPEN')
    def test_duplicate_not_rescheduled(self):
        i=self.intent();self.ctl.execute(i);r=self.ctl.execute(i)
        self.assertTrue(r['duplicate']);self.assertEqual(self.host.jobs.poll(self.jid())['revision'],0)
    def test_operation_id_conflict(self):
        self.call();self.err('CONTROL_CONFLICT',lambda:self.call('cancel',opid=h('op-select')))
    def test_unknown_job_no_journal(self):
        self.err(None,lambda:self.call('select',jid=h('absent')));self.assertEqual(list(self.cr.glob('*.op')),[])
    def test_no_arbitrary_job_submission(self):
        self.assertFalse(hasattr(self.ctl,'submit'));self.err(None,lambda:self.intent('submit'))
    def test_wrong_controller_rejected(self):self.err('STALE_CONTROLLER',lambda:self.call(seed=h('imposter')))
    def test_key_revocation(self):
        self.ctl.replace_controller(None,2);self.err('STALE_CONTROLLER',lambda:self.call('status'))
    def test_key_rotation(self):
        new=h('replacement-seed');self.ctl.replace_controller(self.p.sign_public(new),2)
        self.err('STALE_CONTROLLER',lambda:self.call('status'));self.assertEqual(self.call('status',seed=new,rev=2)['policy_revision'],2)
    def test_policy_revision_must_increase(self):self.err(None,lambda:self.ctl.replace_controller(self.op,1))
    def test_policy_persisted(self):
        self.ctl.replace_controller(self.op,2);self.ctl.close()
        self.err('CONTROL_POLICY',lambda:self.cm.Controller(self.host,self.cr,self.op,1))
        self.ctl=self.cm.Controller(self.host,self.cr,self.op,2);self.assertEqual(self.call('status',rev=2)['policy_revision'],2)
    def test_intent_survives_reopen_without_reexecution(self):
        i=self.intent();self.ctl.execute(i);self.reopen_ctl();r=self.ctl.execute(i);self.assertTrue(r['duplicate'])
    def test_inflight_never_auto_replayed(self):
        i=self.pr.check_intent(self.p,self.kp,self.store_id,self.op,1,self.intent())
        self.ctl.journal.start(i);self.reopen_ctl();r=self.call();self.assertEqual(r['outcome'],'OUTCOME_UNKNOWN');self.assertIsNone(self.host.selected)
    def test_control_pin_detects_missing_record(self):
        self.call('cancel');pin=self.ctl.journal.pin();self.ctl.close()
        for p in self.cr.glob('*.op'):p.unlink()
        self.err('CONTROL_PIN',lambda:self.cm.Controller(self.host,self.cr,self.op,1,expected_pin=pin))
    def test_known_file_disappearance_during_process(self):
        self.call('cancel');next(self.cr.glob('*.op')).unlink();self.err(None,lambda:self.call('status'))
    def test_response_copy_isolated(self):
        r=self.call('cancel');r['job']['state']='QUEUED';self.assertEqual(self.call('status')['job']['state'],'CANCELLED')
    def test_status_does_not_resign_stored_records(self):
        self.call('cancel');before={p.name:p.read_bytes() for p in self.cr.glob('*') if p.is_file()};self.call('status');after={p.name:p.read_bytes() for p in self.cr.glob('*') if p.is_file()};self.assertEqual(before,after)
    def test_cancel_too_late_is_rejected(self):
        self.call();self.complete();self.err(None,lambda:self.call('cancel'))
    def test_same_select_after_completed_returns_current_status(self):
        self.call();self.complete();r=self.call();self.assertTrue(r['duplicate']);self.assertEqual(r['job']['state'],'SUCCEEDED')
    def test_view_rejects_forged_completion_flag(self):
        r=self.call('status');r['job']['result_verified']=True;self.err(None,lambda:self.pr.view_shape(r))
    def test_job_pin_in_status(self):
        r=self.call('status');pin=self.pr.load(bytes.fromhex(r['jobs_pin']),65536);self.assertTrue(self.host.jobs.verify_pin(pin))
    def test_journal_does_not_contain_secret_key(self):
        self.call('cancel')
        for p in self.cr.glob('*'):
            if p.is_file():self.assertNotIn(self.os,p.read_bytes());self.assertNotIn(self.ks,p.read_bytes())
