import errno,json,os,signal,sqlite3,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from gc_support import GCTest,h
from par_wire.codec import encode,decode

EVENTS=['gc_mark.begin','gc_mark.recorded','gc_mark.before_commit','gc_mark.after_commit','gc_mark.ack',
        'gc_sweep.before_unlink','gc_sweep.after_unlink','gc_sweep.after_dirsync','gc_sweep.after_rmdir',
        'gc_sweep.parent_synced','gc_finish.begin','gc_finish.recorded','gc_finish.before_commit','gc_finish.after_commit','gc_finish.ack']
MIGRATION=['gc_migrate.begin','gc_migrate.recorded','gc_migrate.before_commit','gc_migrate.after_commit','gc_migrate.ack']

class GCFaults(GCTest):
    def crash(self,event,occurrence=1,migration=False):
        if migration:
            self.keeper=self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True)
            lid=self.reserve();self.fill(lid);self.seal(lid);self.release(lid);req=b''
        else:lid,req=self.released()
        self.keeper.close()
        j={'root':str(self.path),'seed':self.ks.hex(),'app':self.authority.app,'space':self.authority.space.hex(),
           'head':self.authority.head.hex(),'sequence':self.authority.sequence,'epoch':self.authority.epoch,'issuer':self.authority.issuer.hex(),
           'boot':self.clock.boot.hex(),'ns':self.clock.ns,'quota':self.total*3,'kill':event,'occurrence':occurrence,
           'action':'migration' if migration else 'collect','marker':str(Path(self.tmp.name)/'gc-marker'),
           'lease':lid.hex(),'cap':self.cap.hex(),'request':req.hex()}
        path=Path(self.tmp.name)/'gc-job.json';path.write_text(json.dumps(j))
        r=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('gc_worker.py')),str(path)],capture_output=True,timeout=15)
        self.assertEqual(r.returncode,-signal.SIGKILL,(event,r.stderr.decode()));self.assertEqual(Path(j['marker']).read_text(),event)
        done=event in ('gc_finish.after_commit','gc_finish.ack')
        self.open_keeper(migrate_v1=migration)
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],len(self.bundle.index) if done else self.total)
        if migration:req=self.gc_request(lid)
        a=self.gc(lid,req);self.reopen();self.assertEqual(a,self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],len(self.bundle.index))
        self.assertEqual(self.status(lid)['state'],'RECLAIMED')
    def test_fsync_failure_does_not_refund(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req)
        with patch('os.fsync',side_effect=OSError(errno.ENOSPC,'injected full')):self.err('STORAGE_IO',lambda:self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        self.reopen();self.gc(lid,req)
    def test_unlink_failure_does_not_refund(self):
        lid,req=self.released()
        with patch('os.unlink',side_effect=OSError(errno.EACCES,'injected denied')):self.err('STORAGE_IO',lambda:self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.gc(lid,req)
    def test_rmdir_failure_does_not_refund(self):
        lid,req=self.released()
        with patch('os.rmdir',side_effect=OSError(errno.EIO,'injected io')):self.err('STORAGE_IO',lambda:self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.gc(lid,req)
    def test_writer_contention_prevents_mark(self):
        lid,req=self.released();c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None);c.execute('BEGIN IMMEDIATE')
        try:self.err('SQLITE_BUSY',lambda:self.gc(lid,req))
        finally:c.execute('ROLLBACK');c.close()
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        self.assertTrue(all(self.keeper.object_path(lid,x).exists() for x in self.bundle.objects))
    def test_writer_contention_after_sweep_does_not_refund(self):
        lid,req=self.released();c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None)
        def observe(e):
            if e=='gc_sweep.parent_synced':c.execute('BEGIN IMMEDIATE')
        self.keeper.observer=observe
        try:self.err('SQLITE_BUSY',lambda:self.gc(lid,req))
        finally:
            if c.in_transaction:c.execute('ROLLBACK')
            c.close();self.keeper.observer=None
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.gc(lid,req)
    def test_finish_ack_loss_returns_persisted_same_receipt(self):
        lid,req=self.released()
        def observe(e):
            if e=='gc_finish.after_commit':raise OSError('lost acknowledgment')
        self.keeper.observer=observe;self.err('OUTCOME_UNKNOWN',lambda:self.gc(lid,req));self.keeper.observer=None
        before=self.keeper.diagnostics()['reserved_bytes'];a=self.gc(lid,req);self.assertEqual(a,self.gc(lid,req));self.assertEqual(before,self.keeper.diagnostics()['reserved_bytes'])
    def test_mark_ack_loss_is_resumable(self):
        lid,req=self.released()
        def observe(e):
            if e=='gc_mark.after_commit':raise OSError('lost acknowledgment')
        self.keeper.observer=observe;self.err('OUTCOME_UNKNOWN',lambda:self.gc(lid,req));self.keeper.observer=None
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.gc(lid,req)
    def test_real_sqlite_full_during_mark(self):
        self.path.mkdir();tmp=sqlite3.connect(self.path/'keeper.sqlite');tmp.execute('PRAGMA page_size=512');tmp.execute('VACUUM');tmp.close()
        lid,req=self.released();c=self.keeper.connection;c.execute('PRAGMA wal_checkpoint(TRUNCATE)');pages=c.execute('PRAGMA page_count').fetchone()[0]
        # A small real page size forces the signed intent into new overflow pages; no schema weakening.
        c.execute('PRAGMA max_page_count='+str(pages))
        self.err('SQLITE_FULL',lambda:self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        c.execute('PRAGMA max_page_count=100000');self.gc(lid,req)
    def test_new_process_cannot_open_while_writer_alive(self):
        lid,req=self.released()
        code="from tools.check_keeper_gc import GROUPS; from par_store.fs import WriterLock; from pathlib import Path; WriterLock(Path(__import__('sys').argv[1]))"
        r=subprocess.run([sys.executable,'-c',code,str(self.path)],cwd=Path(__file__).resolve().parents[3],capture_output=True,timeout=10)
        self.assertNotEqual(r.returncode,0);self.assertIn(b'WRITER_BUSY',r.stderr)
    def test_directory_reappears_after_sweep_stops_finish(self):
        lid,req=self.released();path=self.path/'objects'/lid.hex()
        def observe(e):
            if e=='gc_finish.begin':path.mkdir()
        self.keeper.observer=observe;self.err('GC_FILE_CHANGED',lambda:self.gc(lid,req));self.keeper.observer=None
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.gc(lid,req)

def install(event,occurrence=1,migration=False):
    def test(self):self.crash(event,occurrence,migration)
    test.__name__='test_sigkill_'+event.replace('.','_')+('_second' if occurrence==2 else '')
    test.__doc__='Owned child SIGKILL at '+event+' occurrence '+str(occurrence)
    setattr(GCFaults,test.__name__,test)
for e in EVENTS:install(e)
for e in MIGRATION:install(e,migration=True)
for e in ('gc_sweep.after_unlink','gc_sweep.after_dirsync'):install(e,2)
