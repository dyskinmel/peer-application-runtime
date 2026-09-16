from unittest.mock import patch
from retire_control_support import SocketTest,h
class RestartTests(SocketTest):
    def test_restart_tombstone_preserves_job_and_refusal(self):
        d,_=self.ready();self.exchange('submit',d,legacy=True);q=self.retire_request(d)
        self.exchange('retire',d,q);self.whole.close();self.open_host()
        self.assertEqual(self.exchange('status',d)['retirement']['state'],'TOMBSTONED')
        self.err('REMOTE_REJECTED',lambda:self.exchange('submit',d,legacy=True))
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED')
    def test_inflight_registered_reconciles_without_selection(self):
        d,_=self.ready();self.stop_at('submit.after_dispatch',lambda:self.st.submit(d));q=self.retire_request(d)
        with patch.object(self.host.jobs,'submit',side_effect=AssertionError('automatic register')):
            v=self.exchange('reconcile_registration',d,q)
        self.assertEqual(v['stage_state'],'REGISTERED');self.assertIsNone(self.host.selected)
        self.err('REMOTE_REJECTED',lambda:self.exchange('retire',d,q))
        self.assertEqual(self.exchange('retire',d,self.retire_request(d))['retirement']['state'],'TOMBSTONED')
    def test_pending_retirement_reopen_never_auto_deletes(self):
        d,_=self.partial();q=self.retire_request(d)
        def stop(n):
            if n=='submit.retire.before_unlink':raise RuntimeError('before deletion')
        self.st.observer=stop;self.err('REMOTE_UNCERTAIN',lambda:self.exchange('retire',d,q))
        self.st.observer=None;self.whole.close();self.open_host()
        self.assertTrue(self.st.payload_path(self.jid()).exists())
        self.assertEqual(self.exchange('status',d)['retirement']['state'],'INTENT')
        self.assertEqual(self.exchange('retire',d,q)['retirement']['state'],'TOMBSTONED')
    def test_fs_failure_holds_host_until_reopen(self):
        d,_=self.partial();q=self.retire_request(d)
        with patch('par_submit_retire.store.os.fsync',side_effect=OSError('synthetic disk failure')):
            self.err('REMOTE_UNCERTAIN',lambda:self.exchange('retire',d,q))
        self.assertTrue(self.st.poison);self.assertTrue(self.host.fault is not None)
    def test_payload_reappearance_refused_after_restart(self):
        d,_=self.partial();self.exchange('retire',d,self.retire_request(d))
        p=self.st.payload_path(self.jid());p.write_bytes(b'foreign');p.chmod(0o600)
        self.err('REMOTE_REJECTED',lambda:self.exchange('status',d))
    def test_same_uid_foreign_file_not_deleted(self):
        d,_=self.partial();q=self.retire_request(d);p=self.st.payload_path(self.jid());p.write_bytes(b'foreign')
        self.err('REMOTE_REJECTED',lambda:self.exchange('retire',d,q));self.assertEqual(p.read_bytes(),b'foreign')
    def test_control_socket_not_exposed_to_retirement(self):
        from par_job_control import protocol
        self.assertNotIn('retire',protocol.ACTIONS)
    def test_socket_overlap_rejected(self):
        from par_submit_retire_control.host import RetirementControlHost
        self.err('SOCKET_ALIAS',lambda:RetirementControlHost(self.keeper,self.window,self.socket_path,self.upload_path,self.cpath,self.cpath,self.jroot,self.sroot,self.sroot,self.op,1))
