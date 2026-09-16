import os,threading
from unittest.mock import patch
from submission_retire_support import RetireTest,h
class RetirementAudit(RetireTest):
    def test_reappeared_payload_not_deleted_on_duplicate(self):
        d,r=self.partial();q=self.retire_request(d);self.st.retire(q);p=self.st.payload_path(self.jid());p.write_bytes(r[:17]);p.chmod(0o600)
        self.err('RETIRE_PAYLOAD_CHANGED',lambda:self.st.retire(q));self.assertEqual(p.read_bytes(),r[:17])
    def test_known_retirement_record_missing(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));self.st.retirement_path(self.jid()).unlink();self.err(None,lambda:self.st.diagnostics())
    def test_signed_record_byte_flip(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));p=self.st.retirement_path(self.jid());b=bytearray(p.read_bytes());b[-1]^=1;p.write_bytes(b);self.err(None,lambda:self.reopen())
    def test_known_stage_missing(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));self.st._path(self.jid()).unlink();self.err(None,lambda:self.st.diagnostics())
    def test_missing_registered_job_refused(self):
        d,r=self.ready();self.st.submit(d);self.host.jobs.journal.path(self.jid()).unlink();self.err(None,lambda:self.st.retire(self.retire_request(d)));self.assertTrue(self.st.payload_path(self.jid()).exists())
    def test_registered_job_corruption_after_retirement(self):
        d,r=self.ready();self.st.submit(d);self.st.retire(self.retire_request(d));p=self.host.jobs.journal.path(self.jid());b=bytearray(p.read_bytes());b[-1]^=1;p.write_bytes(b);self.err(None,lambda:self.reopen())
    def test_unacknowledged_tail_accounted_as_observed_bytes(self):
        d,r=self.partial();path=self.st.payload_path(self.jid());path.write_bytes(r[:29]);q=self.retire_request(d);v=self.st.retire(q);self.assertEqual(v['removed_payload_bytes'],29)
    def test_changed_confirmed_prefix_blocks_intent(self):
        d,r=self.partial();path=self.st.payload_path(self.jid());path.write_bytes(b'x'*17);self.err(None,lambda:self.retire_request(d));self.assertFalse(self.st.retirement_path(self.jid()).exists())
    def test_replaced_inode_blocks_delete(self):
        d,r=self.partial();q=self.retire_request(d);path=self.st.payload_path(self.jid());backup=self.sroot/'saved';path.rename(backup);path.write_bytes(r[:17]);path.chmod(0o600);backup.unlink()
        self.err('RETIRE_TARGET',lambda:self.st.retire(q));self.assertTrue(path.exists())
    def test_symlink_not_followed(self):
        d,r=self.partial();path=self.st.payload_path(self.jid());other=self.sroot.parent/'protected';other.write_bytes(b'keep');path.unlink();path.symlink_to(other)
        self.err(None,lambda:self.retire_request(d));self.assertEqual(other.read_bytes(),b'keep')
    def test_hardlink_not_unlinked(self):
        d,r=self.partial();path=self.st.payload_path(self.jid());other=self.sroot.parent/'extra-link';os.link(path,other)
        self.err(None,lambda:self.retire_request(d));self.assertTrue(other.exists());self.assertTrue(path.exists())
    def test_unknown_file_rejected(self):
        p=self.sroot/'unknown';p.write_bytes(b'?');p.chmod(0o600);self.err('SUBMIT_LAYOUT',lambda:self.st.audit())
    def test_known_pin_detects_lost_terminal_record_for_empty_payload(self):
        d=self.descriptor();self.st.begin(d);self.st.retire(self.retire_request(d));pin=self.st.pin();self.st.retirement_path(self.jid()).unlink();self.st.close();self.st=None
        self.err('RETIRE_PIN',lambda:self.rm.RetiringSubmissions(self.ctl,self.sroot,expected_pin=pin))
    def test_pin_allows_forward_retirement(self):
        d,r=self.partial();pin=self.st.pin();self.st.retire(self.retire_request(d));self.reopen(expected_pin=pin);self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],0)
    def test_pin_phase_bool_is_rejected(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));pin=self.st.pin();pin[4][0][4]=True;self.err('RETIRE_PIN',lambda:self.st.verify_pin(pin))
    def test_pin_detects_missing_whole_record_pair(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));pin=self.st.pin();self.st.retirement_path(self.jid()).unlink();self.st._path(self.jid()).unlink();self.st.close();self.st=None
        self.err('RETIRE_PIN',lambda:self.rm.RetiringSubmissions(self.ctl,self.sroot,expected_pin=pin))
    def test_wrong_thread_does_not_close_store(self):
        errors=[]
        def other():
            try:self.st.close()
            except Exception as e:errors.append(e.code)
        t=threading.Thread(target=other);t.start();t.join();self.assertEqual(errors,['SUBMIT_OWNER']);self.st.diagnostics()
    def test_fsync_failure_poisoned_until_reopen(self):
        d,r=self.partial();q=self.retire_request(d)
        with patch('par_submit_retire.store.os.fsync',side_effect=OSError('injected sync failure')):
            self.err('RETIRE_JOURNAL_UNCERTAIN',lambda:self.st.retire(q))
        self.assertTrue(self.st.poison);self.assertTrue(self.st.payload_path(self.jid()).exists());self.reopen();self.st.retire(q)
    def test_unlink_failure_does_not_release_quota(self):
        d,r=self.partial();q=self.retire_request(d);target=self.st.payload_path(self.jid());original=type(target).unlink
        def fail(path,*args,**kw):
            if path==target:raise OSError('unlink injected')
            return original(path,*args,**kw)
        with patch.object(type(target),'unlink',fail):self.err('RETIRE_OUTCOME_UNKNOWN',lambda:self.st.retire(q))
        self.reopen();self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],len(r));self.st.retire(q)
    def test_lost_result_after_tombstone_is_idempotent(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_tombstone.after_sync',lambda:self.st.retire(q));self.reopen();v=self.st.retire(q)
        self.assertEqual(v['state'],'TOMBSTONED');self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],0)
    def test_rotation_after_unlink_rebinds_without_recreation(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire.after_unlink',lambda:self.st.retire(q));self.reopen();self.ctl.replace_controller(self.op,2)
        self.err('STALE_CONTROLLER',lambda:self.st.retire(q));q2=self.retire_request(d);self.st.rebind(q2);self.st.retire(q2);self.assertFalse(self.st.payload_path(self.jid()).exists())
    def test_approval_chain_limit(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen()
        for rev in range(2,9):
            self.ctl.replace_controller(self.op,rev);self.st.rebind(self.retire_request(d))
        self.ctl.replace_controller(self.op,9);self.err('RETIRE_CAPACITY',lambda:self.st.rebind(self.retire_request(d)));self.assertTrue(self.st.payload_path(self.jid()).exists())
    def test_rebind_cannot_change_target(self):
        d,r=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen();self.ctl.replace_controller(self.op,2)
        prop=self.st.proposal(d);prop['target']=dict(prop['target']);prop['target'][2]=h('wrong')
        q2=self.rc.make_request(self.p,self.os,self.os,revision=2,nonce=h('n'),**prop);self.err('RETIRE_REBIND',lambda:self.st.rebind(q2))
    def test_retired_record_still_consumes_record_slot(self):
        d,r=self.partial();self.st.retire(self.retire_request(d));self.st.close();p=self.sroot/'CONFIG.cbor';cfg=self.sc.load(p.read_bytes(),4096);cfg[4]=1;p.write_bytes(self.sc.dump(cfg,4096));self.st=None
        self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,max_records=1)
        self.err('SUBMIT_CAPACITY',lambda:self.st.begin(self.descriptor(r,h('new'))))
    def test_reconcile_rejects_unstarted_stage(self):
        d,r=self.partial();self.err('RETIRE_NOT_INFLIGHT',lambda:self.st.reconcile_registration(self.retire_request(d)))
