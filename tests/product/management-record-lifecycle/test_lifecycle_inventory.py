import hashlib,importlib,threading
from pathlib import Path
from submission_retire_support import RetireTest,h
from par_job_control import protocol as control

def files_digest(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

class InventoryTests(RetireTest):
    def setUp(self):
        super().setUp();self.api=importlib.import_module('par_record_lifecycle')
        self.assertTrue(callable(getattr(self.api,'collect_inventory',None)), 'verified cross-ledger collector not implemented')
    def blocked(self,code,fn):
        with self.assertRaises(self.api.LifecycleError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def triple(self):
        d,_=self.ready();self.st.submit(d);self.st.retire(self.retire_request(d))
        raw=control.make_intent(self.p,self.os,keeper=self.kp,store=self.store_id,revision=1,operation_id=h('cancel-control'),action='cancel',job_id=self.jid())
        self.ctl.execute(raw);return d
    def test_empty_real_store(self):
        v=self.api.collect_inventory(self.st);self.assertEqual(v['records'],[]);self.assertEqual(v['source'],'LIVE_READONLY')
    def test_exact_three_ledger_graph(self):
        self.triple();v=self.api.collect_inventory(self.st);self.assertEqual(len(v['records']),3)
        rs={r['kind']:r for r in v['records']};self.assertEqual(rs['job']['state'],'CANCELLED');self.assertEqual(rs['control']['state'],'ACCEPTED');self.assertEqual(rs['submission']['state'],'TOMBSTONED')
        self.assertIn(rs['job']['key'],rs['control']['refs']);self.assertIn(rs['job']['key'],rs['submission']['refs'])
    def test_live_all_terminal_still_blocks_deletion(self):
        self.triple();p=self.api.plan(self.api.collect_inventory(self.st));self.assertFalse(p['model_ready']);self.assertFalse(p['real_deletion_allowed']);self.assertTrue(all(x.startswith('UNMIGRATED:') for x in p['blockers']))
    def test_registered_queued_is_retained(self):
        d,_=self.ready();self.st.submit(d);v=self.api.collect_inventory(self.st);p=self.api.plan(v);self.assertTrue(any(x.startswith('NONTERMINAL:job:') for x in p['blockers']))
    def test_receiving_bytes_accounted(self):
        d,raw=self.partial();v=self.api.collect_inventory(self.st);r=v['records'][0];self.assertEqual(r['kind'],'submission');self.assertEqual(r['reserved_bytes'],len(raw));self.assertGreater(r['storage_bytes'],17)
    def test_no_files_modified(self):
        self.triple();before=files_digest(Path(self.tmp.name));self.api.collect_inventory(self.st);self.assertEqual(files_digest(Path(self.tmp.name)),before)
    def test_no_secrets_or_payload_in_export(self):
        self.triple();raw=self.api.encode_inventory(self.api.collect_inventory(self.st));self.assertNotIn(self.os.hex().encode(),raw);self.assertNotIn(self.ks.hex().encode(),raw);self.assertNotIn(str(self.tmp.name).encode(),raw);self.assertNotIn(b'command',raw)
    def test_no_new_signature_on_collection(self):
        self.triple();old=self.p.sign
        def no_sign(*a,**k):raise AssertionError('read-only collector attempted signing')
        self.p.sign=no_sign
        try:self.api.collect_inventory(self.st)
        finally:self.p.sign=old
    def test_corrupt_job_rejected(self):
        self.triple();p=self.host.jobs.journal.path(self.jid());raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]));self.blocked('SOURCE_REJECTED',lambda:self.api.collect_inventory(self.st))
    def test_missing_registered_job_rejected(self):
        self.triple();self.host.jobs.journal.path(self.jid()).unlink();self.blocked('SOURCE_REJECTED',lambda:self.api.collect_inventory(self.st))
    def test_corrupt_control_rejected(self):
        self.triple();p=self.ctl.journal.path(h('cancel-control'));p.write_bytes(b'bad');self.blocked('SOURCE_REJECTED',lambda:self.api.collect_inventory(self.st))
    def test_corrupt_stage_rejected(self):
        self.partial();self.st._path(self.jid()).write_bytes(b'bad');self.blocked('SOURCE_REJECTED',lambda:self.api.collect_inventory(self.st))
    def test_partial_retirement_is_nonterminal(self):
        d,_=self.partial();q=self.retire_request(d);self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen()
        v=self.api.collect_inventory(self.st);r=v['records'][0];self.assertEqual(r['state'],'INTENT');self.assertIn('NONTERMINAL:'+r['key'],self.api.plan(v)['blockers'])
    def test_inflight_control_stays_unknown(self):
        d,_=self.ready();self.st.submit(d)
        raw=control.make_intent(self.p,self.os,keeper=self.kp,store=self.store_id,revision=1,operation_id=h('unknown'),action='cancel',job_id=self.jid())
        _,i=control.inspect_intent(self.p,raw);self.ctl.journal.start(i)
        v=self.api.collect_inventory(self.st);r=next(r for r in v['records'] if r['kind']=='control');self.assertEqual(r['state'],'INFLIGHT');self.assertIn('NONTERMINAL:'+r['key'],self.api.plan(v)['blockers'])
    def test_snapshot_change_during_collection(self):
        def changed(stage):
            if stage=='between_reads':self.ctl.replace_controller(self.op,2)
        self.blocked('SOURCE_CHANGED',lambda:self.api.collect_inventory(self.st,observer=changed))
    def test_actual_socket_blocks_capture(self):
        sock,hello=self.connect();self.blocked('SOURCE_BUSY',lambda:self.api.collect_inventory(self.st));sock.close();self.tick(3)
    def test_selected_job_blocks_capture(self):
        d,_=self.ready();self.st.submit(d);self.host.schedule(self.jid());self.blocked('SOURCE_BUSY',lambda:self.api.collect_inventory(self.st))
    def test_wrong_thread_refused(self):
        results=[]
        def run():
            try:self.api.collect_inventory(self.st)
            except self.api.LifecycleError as e:results.append(e.code)
        t=threading.Thread(target=run);t.start();t.join();self.assertEqual(results,['SOURCE_REJECTED'])
    def test_controller_revocation_observed(self):
        self.ctl.replace_controller(None,2);v=self.api.collect_inventory(self.st);self.assertIsNone(v['controller']);self.assertEqual(v['controller_revision'],2)
    def test_uncertain_temp_is_not_silently_ignored(self):
        p=self.st.root/'.submit-orphan.tmp';p.write_bytes(b'partial');p.chmod(0o600);self.blocked('UNACKNOWLEDGED_TEMP',lambda:self.api.collect_inventory(self.st));self.assertTrue(p.exists())
    def test_stable_snapshot_bytes(self):
        self.triple();a=self.api.encode_inventory(self.api.collect_inventory(self.st));b=self.api.encode_inventory(self.api.collect_inventory(self.st));self.assertEqual(a,b)
    def test_expected_pin_enforced(self):
        self.triple();pin={'jobs':self.host.jobs.pin(),'control':self.ctl.journal.pin(),'submissions':self.st.pin()};self.api.collect_inventory(self.st,expected_pins=pin)
        self.host.jobs.journal.path(self.jid()).unlink();self.blocked('SOURCE_REJECTED',lambda:self.api.collect_inventory(self.st,expected_pins=pin))
    def test_real_success_keeps_authoritative_effect_reference(self):
        d,_=self.ready();self.st.submit(d);self.st.retire(self.retire_request(d))
        self.host.schedule(self.jid())
        for _ in range(8):
            self.host.tick(0)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
        v=self.api.collect_inventory(self.st)
        r=next(row for row in v['records'] if row['kind']=='job')
        self.assertEqual(r['state'],'SUCCEEDED');self.assertIn('evidence:'+r['evidence_digest'],r['refs'])
        self.assertTrue(any(a['key']=='evidence:'+r['evidence_digest'] for a in v['anchors']))
    def test_real_reopen_does_not_assume_previous_inventory(self):
        self.triple();before=self.api.collect_inventory(self.st);self.reopen()
        self.assertEqual(self.api.collect_inventory(self.st),before)
