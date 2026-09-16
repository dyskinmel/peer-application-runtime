"""Additional negative cases for state/provenance, not hostile target tests."""
import copy,os,socket,threading,time
from unittest.mock import patch
from control_support import ControlTest,h
class ControlHardening(ControlTest):
    def test_bool_policy_in_external_pin_rejected(self):
        p=self.ctl.journal.pin();p[3][0][0]=True;self.err('CONTROL_PIN',lambda:self.ctl.journal.verify_pin(p))
    def test_error_after_dispatch_is_unknown(self):
        original=self.ctl._view
        def boom(*a,**kw):raise OSError('lost status after a successful cancellation')
        with patch.object(self.ctl,'_view',side_effect=boom):self.err('CONTROL_OUTCOME_UNKNOWN',lambda:self.call('cancel'))
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'CANCELLED')
        self.assertTrue(self.call('cancel')['duplicate'])
    def test_pre_dispatch_boundary_interrupt_is_unknown(self):
        self.ctl.journal.observer=lambda e:(_ for _ in ()).throw(OSError('test')) if e=='control.before_dispatch' else None
        self.err('CONTROL_OUTCOME_UNKNOWN',lambda:self.call())
        self.assertIsNone(self.host.selected);self.ctl.journal.observer=None
        self.assertEqual(self.call()['outcome'],'OUTCOME_UNKNOWN')
    def test_future_signature_does_not_select_old_policy(self):
        self.err('STALE_CONTROLLER',lambda:self.call(rev=2));self.assertEqual(list(self.cr.glob('*.op')),[])
    def test_journal_path_overlap(self):
        self.err('CONTROL_PATH',lambda:self.cm.Controller(self.host,self.jroot/'inside',self.op,1))
    def test_unsafe_journal_permissions(self):
        self.cr.chmod(0o755);self.err(None,lambda:self.call('status'));self.cr.chmod(0o700)
    def test_journal_owner_fork_rejected(self):
        import json
        r,w=os.pipe();pid=os.fork()
        if pid==0:
            os.close(r)
            try:self.ctl.execute(self.intent());code='BAD'
            except Exception as e:code=e.code
            os.write(w,code.encode());os._exit(0)
        os.close(w);result=os.read(r,100);os.close(r);os.waitpid(pid,0)
        self.assertEqual(result,b'SCHEDULER_OWNER');self.assertIsNone(self.host.selected)
    def test_reconcile_then_retry_is_explicit(self):
        self.host.schedule(self.jid());self.tick(2)
        self.host.jobs.journal.observer=lambda e:(_ for _ in ()).throw(OSError('test')) if e=='job.effect.before_dispatch' else None
        self.tick();self.host.jobs.journal.observer=None
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'OUTCOME_UNKNOWN')
        r=self.call('reconcile');self.assertEqual(r['job']['state'],'RETRY_READY');self.tick(3);self.assertEqual(self.window.phase,'OPEN')
        r=self.call('retry');self.assertEqual(r['outcome'],'ACCEPTED');self.tick();self.assertEqual(self.window.phase,'CLOSED')
    def test_fake_cancellable_rejected(self):
        r=self.call('status');r['job']['cancellable']=False;self.err(None,lambda:self.pr.view_shape(r))
    def test_fake_journal_state_rejected(self):
        r=self.call('status');r['job']['journal_state']='EXECUTING';self.err(None,lambda:self.pr.view_shape(r))
    def test_fake_reconciliation_flag_rejected(self):
        r=self.call('status');r['job']['requires_reconciliation']=True;self.err(None,lambda:self.pr.view_shape(r))
