import errno,json,os,signal,subprocess,sys
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from retire_support import RetireTest,h
from par_wire.codec import encode
from par_keeper.contract import authority_body
from par_keeper_upload.spool import Spool

class RetireFaults(RetireTest):
    def prepared(self):
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]));return t,self.retirement_request()
    def pause(self,event,req):
        def stop(e):
            if e==event:raise OSError(errno.EIO,'injected interruption')
        self.spool.observer=stop;self.err('OUTCOME_UNKNOWN',lambda:self.spool.retire(req));self.reopen()
    def crash(self,action,event):
        if action=='migrate':
            self.spool.close();self.stage_root=self.path/'legacy';self.spool=Spool(self.keeper,self.stage_root)
        t,q=self.prepared()
        if action=='rebind':
            self.pause('retirement.intent.after_meta',q);self.change_authority();q=self.retirement_request()
        job=Path(self.tmp.name)/'retirement-worker.json'
        job.write_text(json.dumps({'root':str(self.path),'stage_root':str(self.stage_root),'seed':self.ks.hex(),
            'authority':encode(authority_body(self.authority)).hex(),'quota':self.total*3,
            'event':event,'action':action,'request':q.hex()}));job.chmod(0o600)
        self.spool.close();self.spool=None;self.keeper.close();self.keeper=None
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('retire_crash_worker.py')),str(job)],
            capture_output=True,timeout=12,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());hit=json.loads(cp.stdout)
        self.assertEqual(hit['hit'],event);self.assertEqual(hit['pgid'],os.getpgid(0))
        self.open_keeper();self.spool=self.spooltype(self.keeper,self.stage_root,allow_migrate=True)
        if action=='rebind':self.spool.rebind(q)
        if action=='migrate':self.assertTrue(self.part(t).exists())
        first=self.spool.retire(q);second=self.spool.retire(q)
        self.assertEqual(first,second);self.assertFalse(self.part(t).exists());self.assertEqual(self.spool.diagnostics()['reserved_bytes'],0)
        self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_initial_journal_fsync_failure_preserves_payload(self):
        t,q=self.prepared()
        with patch('par_keeper_upload_retire.spool.os.fsync',side_effect=OSError(errno.EIO,'synthetic fsync')):
            self.err('OUTCOME_UNKNOWN',lambda:self.spool.retire(q))
        self.reopen();self.assertTrue(self.part(t).exists());self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0)
        self.spool.retire(q)
    def test_unlink_failure_does_not_credit(self):
        t,q=self.prepared();original=Path.unlink
        def bad(path,*a,**kw):
            if path.suffix=='.part':raise OSError(errno.EIO,'synthetic unlink')
            return original(path,*a,**kw)
        with patch.object(Path,'unlink',bad):self.err('OUTCOME_UNKNOWN',lambda:self.spool.retire(q))
        self.reopen();self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0);self.spool.retire(q)
    def test_after_unlink_before_sync_still_charged(self):
        t,q=self.prepared();self.pause('retirement.after_unlink',q)
        self.assertFalse(self.part(t).exists());self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0)
        self.spool.retire(q);self.assertEqual(self.spool.diagnostics()['reserved_bytes'],0)
    def test_removed_marker_is_not_credit(self):
        t,q=self.prepared();self.pause('retirement.removed.after_meta',q)
        self.assertEqual(self.spool.retirement_status(t)['state'],'PAYLOAD_REMOVED')
        self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0);self.spool.retire(q)
    def test_lost_final_ack_replays_same_receipt(self):
        t,q=self.prepared();self.pause('retirement.ack',q)
        self.assertEqual(self.spool.retire(q),self.spool.retire(q))
        self.assertEqual(self.spool.diagnostics()['reserved_bytes'],0)
    def test_auth_change_before_unlink_prevents_removal(self):
        t,q=self.prepared()
        def change(e):
            if e=='retirement.before_unlink':self.change_authority()
        self.spool.observer=change;self.err('STALE_AUTHORITY',lambda:self.spool.retire(q))
        self.assertTrue(self.part(t).exists());self.spool.observer=None
        q2=self.retirement_request();self.spool.rebind(q2);self.spool.retire(q2)
    def test_auth_change_after_unlink_keeps_charge_until_rebind(self):
        t,q=self.prepared()
        def change(e):
            if e=='retirement.after_unlink':self.change_authority()
        self.spool.observer=change;self.err('STALE_AUTHORITY',lambda:self.spool.retire(q));self.spool.observer=None
        self.assertFalse(self.part(t).exists());self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0)
        q2=self.retirement_request();self.spool.rebind(q2);self.spool.retire(q2)
    def test_payload_change_at_last_boundary_rejected(self):
        t,q=self.prepared()
        def change(e):
            if e=='retirement.before_unlink':self.part(t).write_bytes(b'x'*16)
        self.spool.observer=change;self.err('RETIREMENT_PAYLOAD_CHANGED',lambda:self.spool.retire(q))
        self.assertEqual(self.part(t).read_bytes(),b'x'*16)
    def test_reentrant_upload_blocked(self):
        t,q=self.prepared();hit=[]
        def attempt(e):
            if e=='retirement.before_unlink':
                self.err('OWNER_REQUIRED',lambda:self.spool.execute(self.beginraw));hit.append(e)
        self.spool.observer=attempt;self.spool.retire(q);self.assertEqual(len(hit),1)
    def test_keeper_storage_uncertain_blocks_retire(self):
        t,q=self.prepared();self.keeper._uncertain=True
        self.err('STORAGE_UNCERTAIN',lambda:self.spool.retire(q));self.keeper._uncertain=False
        self.assertTrue(self.part(t).exists())
    def test_no_sqlite_writes_by_retirement(self):
        t,q=self.prepared();seen=[]
        self.keeper.connection.set_trace_callback(seen.append)
        self.spool.retire(q);self.keeper.connection.set_trace_callback(None)
        self.assertFalse(any(sql.upper().startswith(('INSERT','UPDATE','DELETE','BEGIN')) for sql in seen),seen)
    def test_capacity_is_not_credited_during_tombstone_write(self):
        t,q=self.prepared();seen=[]
        def inspect(e):
            if e=='retirement.tombstone.before_meta':
                m,b=self.spool._records()[0];seen.append(m[5])
        self.spool.observer=inspect;self.spool.retire(q);self.assertEqual(seen,['active'])
    def test_enospc_metadata_does_not_delete_payload(self):
        t,q=self.prepared()
        with patch('par_keeper_upload.spool.tempfile.mkstemp',side_effect=OSError(errno.ENOSPC,'synthetic disk full')):
            self.err('OUTCOME_UNKNOWN',lambda:self.spool.retire(q))
        self.reopen();self.assertTrue(self.part(t).exists())

BOUNDARIES={
 'retire':['retirement.intent.before_meta','retirement.intent.after_replace','retirement.intent.after_meta',
    'retirement.before_unlink','retirement.after_unlink','retirement.after_sync',
    'retirement.removed.before_meta','retirement.removed.after_replace','retirement.removed.after_meta',
    'retirement.before_credit','retirement.tombstone.before_meta','retirement.tombstone.after_replace',
    'retirement.tombstone.after_meta','retirement.ack'],
 'rebind':['retirement.rebind.before_meta','retirement.rebind.after_replace','retirement.rebind.after_meta'],
 'migrate':['retirement.migrate.before_meta','retirement.migrate.after_replace','retirement.migrate.after_meta']}
for action,events in BOUNDARIES.items():
    for event in events:
        def test(self,a=action,e=event):self.crash(a,e)
        name='test_sigkill_'+action+'_'+event.replace('.','_')
        if hasattr(RetireFaults,name):raise RuntimeError('duplicate test ID: '+name)
        setattr(RetireFaults,name,test)
