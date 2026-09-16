import errno,json,os,signal,sqlite3,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from repair_support import RepairTest,h,replace
from par_keeper.contract import split,authority_body,dump
from par_keeper_gc import KeeperGC
from par_keeper_repair.contract import job_id

REPAIR_EVENTS=['repair_mark.begin','repair_mark.recorded','repair_mark.before_commit','repair_mark.after_commit','repair_mark.ack',
    'repair_file.written','repair_file.synced','repair_file.staged','repair_file.before_replace','repair_file.replaced','repair_file.durable',
    'repair_cleanup.removed','repair_cleanup.durable','repair_finish.begin','repair_finish.recorded','repair_finish.before_commit','repair_finish.after_commit','repair_finish.ack']
CANCEL_EVENTS=['repair_abort_mark.begin','repair_abort_mark.recorded','repair_abort_mark.before_commit','repair_abort_mark.after_commit','repair_abort_mark.ack',
    'repair_cleanup.unlinked','repair_cleanup.removed','repair_cleanup.durable','repair_abort_finish.begin','repair_abort_finish.recorded','repair_abort_finish.before_commit','repair_abort_finish.after_commit','repair_abort_finish.ack']
MIGRATION_EVENTS=['repair_migrate.begin','repair_migrate.recorded','repair_migrate.before_commit','repair_migrate.after_commit','repair_migrate.ack']

class RepairFaults(RepairTest):
    def make_partial(self,lid,req):
        def observe(e):
            if e=='repair_file.synced':raise OSError('stop with stage')
        self.keeper.observer=observe;self.err('STORAGE_IO',lambda:self.repair(lid,req));self.keeper.observer=None
    def crash(self,event,action='repair',occurrence=1):
        if action=='migration':
            self.keeper=KeeperGC(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True)
            lid=self.reserve();self.fill(lid);self.seal(lid)
        else:lid,_=self.ready()
        oids=sorted(self.bundle.objects)[:2]
        for oid in oids:self.damage(lid,'corrupt',oid)
        req=self.repair_request(lid,oids);cancel=b''
        if action=='cancel':
            self.make_partial(lid,req);cancel=self.cancel_request(lid,job_id(split(req)[0]))
        old=dict(self.keeper._lease(lid));self.keeper.close()
        j={'root':str(self.path),'seed':self.ks.hex(),'app':self.authority.app,'space':self.authority.space.hex(),'head':self.authority.head.hex(),
            'sequence':self.authority.sequence,'epoch':self.authority.epoch,'issuer':self.authority.issuer.hex(),'boot':self.clock.boot.hex(),'ns':self.clock.ns,
            'quota':self.total*3,'kill':event,'occurrence':occurrence,'action':action,'marker':str(Path(self.tmp.name)/'repair-marker'),
            'lease':lid.hex(),'cap':self.cap.hex(),'request':req.hex(),'cancel':cancel.hex(),'objects':{i.hex():self.bundle.objects[i].hex() for i in oids}}
        jp=Path(self.tmp.name)/'repair-job.json';jp.write_text(json.dumps(j))
        r=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('repair_worker.py')),str(jp)],capture_output=True,timeout=15)
        self.assertEqual(r.returncode,-signal.SIGKILL,(event,r.stderr.decode()));self.assertEqual(Path(j['marker']).read_text(),event)
        self.open_keeper(migrate_v2=action=='migration')
        self.assertEqual(dict(self.keeper._lease(lid)),old);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        if action=='cancel':
            a=self.keeper.cancel_repair(lid,self.cap,cancel);self.reopen();self.assertEqual(a,self.keeper.cancel_repair(lid,self.cap,cancel))
            self.assertEqual(self.keeper.diagnostics()['repair_staging_reserved_bytes'],0)
        else:
            a=self.repair(lid,req);self.reopen();self.assertEqual(a,self.repair(lid,req));self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
        self.assertEqual(dict(self.keeper._lease(lid)),old)
    def test_replace_failure_is_resumable(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid])
        with patch('par_keeper_repair.filesystem.os.replace',side_effect=OSError(errno.EIO,'replace')):self.err('STORAGE_IO',lambda:self.repair(lid,req))
        self.assertFalse(self.keeper.object_path(lid,oid).exists());self.reopen();self.repair(lid,req)
    def test_fsync_failure_keeps_quota(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid])
        with patch('os.fsync',side_effect=OSError(errno.ENOSPC,'full')):self.err('STORAGE_IO',lambda:self.repair(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.reopen();self.repair(lid,req)
    def test_writer_busy_before_intent_no_publication(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None);c.execute('BEGIN IMMEDIATE')
        try:self.err('SQLITE_BUSY',lambda:self.repair(lid,req))
        finally:c.execute('ROLLBACK');c.close()
        self.assertFalse(self.keeper.object_path(lid,oid).exists());self.repair(lid,req)
    def test_writer_busy_after_publication_resumes(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None)
        def observe(e):
            if e=='repair_cleanup.durable':c.execute('BEGIN IMMEDIATE')
        self.keeper.observer=observe
        try:self.err('SQLITE_BUSY',lambda:self.repair(lid,req))
        finally:
            if c.in_transaction:c.execute('ROLLBACK')
            c.close();self.keeper.observer=None
        self.assertEqual(self.keeper.object_path(lid,oid).read_bytes(),self.bundle.objects[oid]);self.repair(lid,req)
    def test_finished_ack_loss_uses_same_signed_result(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid])
        def observe(e):
            if e=='repair_finish.after_commit':raise OSError('response lost')
        self.keeper.observer=observe;self.err('OUTCOME_UNKNOWN',lambda:self.repair(lid,req));self.keeper.observer=None
        a=self.keeper._repair_job(job_id(split(req)[0]))['result'];self.reopen();self.assertEqual(a,self.repair(lid,req))
    def test_real_sqlite_full_on_mark(self):
        self.path.mkdir();c=sqlite3.connect(self.path/'keeper.sqlite');c.execute('PRAGMA page_size=512');c.execute('VACUUM');c.close()
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);c=self.keeper.connection;c.execute('PRAGMA wal_checkpoint(TRUNCATE)');pages=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(pages))
        self.err('SQLITE_FULL',lambda:self.repair(lid,req));self.assertFalse(self.keeper.object_path(lid,oid).exists());c.execute('PRAGMA max_page_count=100000');self.repair(lid,req)
    def test_target_changed_before_replace_rejected(self):
        lid,_=self.ready();oid=self.damage(lid,'corrupt');req=self.repair_request(lid,[oid]);p=self.keeper.object_path(lid,oid)
        def observe(e):
            if e=='repair_file.before_replace':p.write_bytes(b'new-data')
        self.keeper.observer=observe;self.err('REPAIR_FILE_CHANGED',lambda:self.repair(lid,req));self.keeper.observer=None;self.assertEqual(p.read_bytes(),b'new-data');self.repair(lid,req)
    def test_metadata_authority_changed_before_replace_rejected(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);new=replace(self.authority,head=h('new-head'),sequence=2)
        def observe(e):
            if e=='repair_file.before_replace':self.keeper.connection.execute('UPDATE metadata SET authority=?',(dump(authority_body(new)),))
        self.keeper.observer=observe;self.err('STALE_AUTHORITY',lambda:self.repair(lid,req));self.keeper.observer=None;self.assertFalse(self.keeper.object_path(lid,oid).exists())
    def test_reentrant_release_is_rejected(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid])
        def observe(e):
            if e=='repair_file.staged':self.release(lid)
        self.keeper.observer=observe;self.err('REENTRANT_OPERATION',lambda:self.repair(lid,req));self.keeper.observer=None;self.assertEqual(self.keeper._lease(lid)['state'],'sealed')
    def test_pending_restart_preserves_staging_reservation(self):
        lid,_=self.ready();req=self.repair_request(lid);before=self.keeper.mark_repair(lid,self.cap,req);a=self.keeper.diagnostics()['repair_staging_reserved_bytes'];self.reopen();self.assertEqual(self.keeper.diagnostics()['repair_staging_reserved_bytes'],a)
    def test_abort_cleanup_failure_does_not_release_stage_budget(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);self.make_partial(lid,req);jid=job_id(split(req)[0]);cancel=self.cancel_request(lid,jid)
        with patch('par_keeper_repair.filesystem.os.unlink',side_effect=OSError(errno.EIO,'unlink')):self.err('STORAGE_IO',lambda:self.keeper.cancel_repair(lid,self.cap,cancel))
        self.assertGreater(self.keeper.diagnostics()['repair_staging_reserved_bytes'],0);self.reopen();self.keeper.cancel_repair(lid,self.cap,cancel)

def install(event,action='repair',occurrence=1):
    def test(self):self.crash(event,action,occurrence)
    test.__name__='test_sigkill_'+action+'_'+event.replace('.','_')+('_second' if occurrence==2 else '')
    setattr(RepairFaults,test.__name__,test)
for e in REPAIR_EVENTS:install(e)
for e in CANCEL_EVENTS:install(e,'cancel')
for e in MIGRATION_EVENTS:install(e,'migration')
for e in ('repair_file.replaced','repair_file.durable'):install(e,occurrence=2)
