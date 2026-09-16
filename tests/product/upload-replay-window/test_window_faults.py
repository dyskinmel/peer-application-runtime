import errno,json,os,signal,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from window_support import WindowTest,h
from par_upload_window import contract as c
from par_keeper.contract import authority_body
from par_wire.codec import encode
class WindowFaults(WindowTest):
    def pause(self,event,fn):
        def fail(e):
            if e==event:raise OSError(errno.EIO,'injected failure')
        self.window.observer=fail;self.err('OUTCOME_UNKNOWN',fn);self.reopen_window()
    def test_binding_without_stage_blocks_close_until_retry(self):
        raw=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),__import__('hashlib').sha256(self.bundle.index).digest()]);wrapped=self.wrap(raw)
        self.pause('window.bind.after_sync',lambda:self.window.execute(wrapped));self.err('WINDOW_NOT_TERMINAL',self.window.export_archive)
        self.beginraw=raw;self.window.execute(wrapped);self.retire_stage();self.finish()
    def test_archive_synced_without_barrier_blocks_new_commands(self):
        self.terminal();a,q=self.proposed();self.pause('window.archive.after_sync',lambda:self.window.close_window(q,a))
        self.err('WINDOW_CLOSE_PREPARED',lambda:self.window.execute(self.beginwrapped));self.window.close_window(q,a);self.window.compact()
    def test_closed_reopen_does_not_delete_automatically(self):
        t=self.terminal();a,q=self.proposed();self.pause('window.close.after_sync',lambda:self.window.close_window(q,a));self.assertTrue(self.live(t).exists());self.window.compact()
    def test_unlink_failure_keeps_slots_reserved(self):
        self.terminal();a,q=self.proposed();self.window.close_window(q,a)
        with patch('pathlib.Path.unlink',side_effect=OSError(errno.EACCES,'injected unlink')):self.err('OUTCOME_UNKNOWN',self.window.compact)
        self.reopen_window();self.assertEqual(self.window.diagnostics()['records'],1);self.window.compact()
    def test_sync_failure_does_not_credit_early(self):
        self.terminal();a,q=self.proposed();self.window.close_window(q,a)
        self.pause('window.compact.after_unlink',self.window.compact);self.assertEqual(self.window.diagnostics()['records'],1);self.window.compact()
    def test_state_fsync_failure_preserves_old_metadata(self):
        t=self.terminal();a,q=self.proposed()
        with patch('par_upload_window.store.os.fsync',side_effect=OSError(errno.ENOSPC,'injected capacity')):self.err('OUTCOME_UNKNOWN',lambda:self.window.close_window(q,a))
        self.reopen_window();self.assertTrue(self.live(t).exists());self.window.close_window(q,a);self.window.compact()
    def test_no_authority_change_before_close_barrier(self):
        t=self.terminal();a,q=self.proposed()
        def change(e):
            if e=='window.close.before_barrier':self.change_authority()
        self.window.observer=change;self.err('STALE_AUTHORITY',lambda:self.window.close_window(q,a));self.assertTrue(self.live(t).exists())
        self.reopen_window();q=c.approve_close(self.p,self.s.owner,self.keeper.authority,self.grant,a,h('new-close'));self.window.close_window(q,a);self.window.compact()
    def test_tamper_immediately_before_unlink_preserves_foreign_file(self):
        t=self.terminal();a,q=self.proposed();self.window.close_window(q,a)
        first=self.wroot/'bindings'/(t.hex()+'.bound')
        def change(e):
            if e=='window.compact.before_unlink':first.write_bytes(b'foreign')
        self.window.observer=change;self.err('WINDOW_RECORD_CHANGED',self.window.compact);self.assertEqual(first.read_bytes(),b'foreign')
    def crash(self,action,event,occurrence=1):
        self.terminal();archive,req=self.proposed();args=[req,archive]
        if action=='compact':self.window.close_window(req,archive);args=[]
        if action=='open_window':
            self.window.close_window(req,archive);rec=self.window.compact();new=self.grant_for(2,c.digest(rec));args=[new]
        if action=='execute':
            raw=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),__import__('hashlib').sha256(self.bundle.index).digest()]);args=[self.wrap(raw)]
        if action=='abandon':
            raw=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),__import__('hashlib').sha256(self.bundle.index).digest()])
            def stop(e):
                if e=='window.bind.after_sync':raise OSError(errno.EIO,'synthetic interrupted begin')
            self.window.observer=stop;self.err('OUTCOME_UNKNOWN',lambda:self.window.execute(self.wrap(raw)));self.reopen_window()
            self.beginraw=raw;self.change_authority();args=[self.wrap(self.retirement_request(),'retire')]
        job=Path(self.tmp.name)/'window-worker.json';job.write_text(json.dumps({'keeper_root':str(self.path),'root':str(self.wroot),'store_id':self.store_id.hex(),'seed':self.ks.hex(),'authority':encode(authority_body(self.keeper.authority)).hex(),'quota':self.total*3,'action':'execute' if action=='abandon' else action,'event':event,'occurrence':occurrence,'args':[x.hex() for x in args]}));job.chmod(0o600)
        self.window.close();self.window=None;self.keeper.close();self.keeper=None
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('window_crash_worker.py')),str(job)],capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());record=json.loads(cp.stdout)
        self.assertEqual((record['hit'],record['occurrence'],record['pgid']),(event,occurrence,os.getpgid(0)))
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id)
        if action=='execute':
            self.beginraw=raw;self.window.execute(args[0]);self.retire_stage();archive,req=self.proposed()
        if action=='abandon':
            self.window.execute(args[0]);archive,req=self.proposed()
        if action=='open_window':
            self.grant=new;self.window.open_window(new);self.err('WINDOW_SCOPE',lambda:self.window.execute(self.beginwrapped));return
        self.window.close_window(req,archive);r=self.window.compact();self.assertEqual(r,self.window.compact())
        self.assertEqual(self.window.diagnostics()['records'],0);self.next_window(r)
        self.err('WINDOW_SCOPE',lambda:self.window.execute(self.beginwrapped))
BOUNDARIES={
 'close_window':['window.archive.before_replace','window.archive.after_replace','window.archive.after_sync','window.close.before_barrier','window.close.before_replace','window.close.after_replace','window.close.after_sync'],
 'compact':['window.compact.before_unlink','window.compact.after_unlink','window.compact.after_unlink_sync','window.compact.before_credit','window.compact.before_replace','window.compact.after_replace','window.compact.after_sync','window.compact.ack'],
 'open_window':['window.open.before_commit','window.open.before_replace','window.open.after_replace','window.open.after_sync'],
 'abandon':['window.abandon.authorized','window.abandon.before_meta','window.abandon.after_replace','window.abandon.after_meta'],
 'execute':['window.bind.before_commit','window.bind.before_replace','window.bind.after_replace','window.bind.after_sync']}
for action,events in BOUNDARIES.items():
    for event in events:
        def test(self,a=action,e=event):self.crash(a,e)
        name='test_sigkill_'+action+'_'+event.replace('.','_')
        if hasattr(WindowFaults,name):raise RuntimeError('duplicate test ID')
        setattr(WindowFaults,name,test)
def partial(self):self.crash('compact','window.compact.after_unlink',2)
WindowFaults.test_sigkill_compact_second_record=partial
