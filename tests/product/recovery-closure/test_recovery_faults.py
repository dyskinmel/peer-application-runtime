from recovery_support import *
import subprocess,sys,signal,os,shutil,threading
from unittest.mock import patch
WORKER=Path(__file__).with_name('recovery_worker.py')
EVENTS=['object.written','object.synced','object.published','object.durable','object.ack',
        'finalize.verified','finalize.stage_verified','finalize.published','finalize.durable','finalize.ack']
class Faults(RecoveryTest):
    def test_receive_fsync_failure_not_completed(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';oid=next(iter(b.objects))
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            with patch('par_recovery.transfer.os.fsync',side_effect=OSError('disk full')):
                self.reject_rc('TRANSFER_IO',lambda:rx.put(oid,b.objects[oid]))
            self.assertIn(oid,rx.missing())
    def test_no_space_before_publish(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';oid=next(iter(b.objects))
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            with patch('par_recovery.transfer.tempfile.mkstemp',side_effect=OSError(28,'disk full')):
                self.reject_rc('TRANSFER_IO',lambda:rx.put(oid,b.objects[oid]))
            self.assertIn(oid,rx.missing())
    def test_lost_object_reply_replays_identical(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';oid=next(iter(b.objects))
        def lost(e):
            if e=='object.ack':raise RuntimeError('lost')
        with self.rc.Inbox(root,b.index,self.pin(b),observer=lost) as rx:
            self.reject_rc('TRANSFER_OUTCOME_UNKNOWN',lambda:rx.put(oid,b.objects[oid]));rx.observer=None
            self.assertEqual(rx.put(oid,b.objects[oid]),'DUPLICATE')
    def test_lost_finalize_reply_reopen(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';dest=Path(self.tmp.name)/'recovered'
        def lost(e):
            if e=='finalize.ack':raise RuntimeError('lost')
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            for i,r in b.objects.items():rx.put(i,r)
            rx.observer=lost;self.reject_rc('RECOVERY_OUTCOME_UNKNOWN',lambda:rx.finalize(dest,self.p,self.reader['secret']))
        self.assertEqual(self.rc.open_recovery(dest,self.pin(b),self.p,self.reader['secret']).status()['state'],'RECIPIENT_VALIDATED_READ_ONLY')
    def test_reentrant_receive_refused(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';oid=next(iter(b.objects));seen=[]
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            def callback(e):
                if e=='object.written':
                    try:rx.put(oid,b.objects[oid])
                    except self.rc.RecoveryError as ex:seen.append(ex.code)
            rx.observer=callback;rx.put(oid,b.objects[oid])
        self.assertEqual(seen,['REENTRANT_OPERATION'])
    def test_cross_thread_refused(self):
        b=self.collect();seen=[]
        with self.rc.Inbox(Path(self.tmp.name)/'inbox',b.index,self.pin(b)) as rx:
            def run():
                try:rx.missing()
                except self.rc.RecoveryError as ex:seen.append(ex.code)
            t=threading.Thread(target=run);t.start();t.join()
        self.assertEqual(seen,['WRONG_THREAD'])
    def test_donor_db_removed_then_fresh_process_recovers(self):
        b=self.collect();source=self.publish(b);pinfile=self.trusted_file(b)
        self.close();shutil.rmtree(self.root);self.source.unlink()
        dest=Path(self.tmp.name)/'recovered';inbox=Path(self.tmp.name)/'inbox'
        r=subprocess.run([sys.executable,'-I','-S',str(WORKER),'receive',str(source),str(inbox),str(dest),str(pinfile),'none'],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr)
        r=subprocess.run([sys.executable,'-I','-S',str(WORKER),'open',str(dest),str(inbox),str(self.output),str(pinfile),'none'],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.output.read_bytes(),self.data)
    def test_reopen_does_not_accept_claim_file(self):
        b=self.collect();root=self.publish(b);(root/'VALIDATED.json').write_text('{"valid":true}')
        self.reject_rc('UNEXPECTED_FILE',lambda:self.rc.open_recovery(root,self.pin(b),self.p,self.reader['secret']))

    def test_temporary_cleanup_failure_preserves_unknown_result(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox';oid=next(iter(b.objects))
        real=Path.unlink
        def failed(path,*args,**kw):
            if path.name.startswith('.rc-part-'):raise OSError('cleanup unavailable')
            return real(path,*args,**kw)
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            with patch.object(Path,'unlink',failed):
                self.reject_rc('TRANSFER_OUTCOME_UNKNOWN',lambda:rx.put(oid,b.objects[oid]))
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:self.assertNotIn(oid,rx.missing())
    def test_initial_directory_failure_stable_error(self):
        b=self.collect();root=Path(self.tmp.name)/'inbox'
        with patch('par_recovery.transfer.os.fsync',side_effect=OSError('disk full')):
            self.reject_rc('TRANSFER_IO',lambda:self.rc.Inbox(root,b.index,self.pin(b)))

def _crash(event):
    def run(self):
        b=self.collect();source=self.publish(b);pinfile=self.trusted_file(b);root=Path(self.tmp.name)/'inbox';dest=Path(self.tmp.name)/'recovered'
        proc=subprocess.run([sys.executable,'-I','-S',str(WORKER),'receive',str(source),str(root),str(dest),str(pinfile),event],capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,-signal.SIGKILL,proc.stderr)
        # No stale process is left: subprocess.run has reaped exactly this owned PID.
        with self.rc.Inbox(root,b.index,self.pin(b)) as rx:
            while rx.missing():rx.pull(self.rc.DirectoryProvider(source,b.index,self.pin(b)),limit=32)
            if not dest.exists():rx.finalize(dest,self.p,self.reader['secret'])
        v=self.rc.open_recovery(dest,self.pin(b),self.p,self.reader['secret']);v.export_file(self.receipt.envelope_id,self.output)
        self.assertEqual(self.output.read_bytes(),self.data);self.assertFalse(v.status()['applied'])
    return run
for event in EVENTS:setattr(Faults,'test_sigkill_'+event.replace('.','_'),_crash(event))
