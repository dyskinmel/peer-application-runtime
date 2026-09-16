import errno,hashlib,json,os,signal,sqlite3,subprocess,sys
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from upload_support import UploadTest,h,pr,reserve_payload,pin_values
from par_keeper.contract import authority_body
from par_wire.codec import encode

class UploadFaults(UploadTest):
    def prepared(self,action):
        if action=='begin':return self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()])
        if action=='chunk':return self.cmd('chunk',[self.begin_index(),0,self.bundle.index])
        if action=='reserve':
            t=self.begin_index();self.chunks(t,self.bundle.index);self.rescall=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30))
            return self.cmd('reserve',[t,pin_values(self.rpin),30],call=self.rescall)
        lid=self.upload_index()
        if action=='put':
            t,oid,raw,call=self.begin_object(lid);self.chunks(t,raw,lid)
            return self.cmd('put',t,lid,call)
        for oid in self.bundle.objects:self.upload_object(lid,oid)
        return self.cmd('seal',None,lid,self.call('seal',lid))
    def crash(self,action,event):
        command=self.prepared(action)
        job=Path(self.tmp.name)/'crash.json';job.write_text(json.dumps({'root':str(self.path),'seed':self.ks.hex(),'authority':encode(authority_body(self.authority)).hex(),'quota':self.total*3,'event':event,'command':command.hex()}));job.chmod(0o600)
        self.spool.close();self.spool=None;self.keeper.close();self.keeper=None
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('upload_crash_worker.py')),str(job)],capture_output=True,timeout=10,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());self.assertEqual(json.loads(cp.stdout)['hit'],event)
        self.open_keeper();self.spool=self.spooltype(self.keeper,self.stage_root)
        one=self.spool.execute(command);two=self.spool.execute(command);self.assertEqual(one,two)
        self.assertLessEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        if action=='seal':self.assertEqual(self.status(self.lid)['generation'],1)
    def test_lost_stage_ack_requires_reopen(self):
        t=self.begin_index();q=self.cmd('chunk',[t,0,self.bundle.index])
        def fail(e):
            if e=='chunk.after_meta':raise OSError(errno.EIO,'synthetic lost ack')
        self.spool.observer=fail;self.err('OUTCOME_UNKNOWN',lambda:self.spool.execute(q));self.reopen()
        self.assertEqual(self.spool.execute(q)[1],len(self.bundle.index))
    def test_authority_change_during_chunk_does_not_ack(self):
        t=self.begin_index();q=self.cmd('chunk',[t,0,self.bundle.index])
        def update(e):
            if e=='chunk.after_fsync':self.keeper.update_authority(replace(self.authority,head=h('new-head'),sequence=2))
        self.spool.observer=update;self.err(None,lambda:self.spool.execute(q));self.reopen()
        m,_=self.spool._meta(t);self.assertEqual(m[3],0)
    def test_actual_sqlite_lock_does_not_reserve(self):
        q=self.prepared('reserve');c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None)
        try:
            c.execute('BEGIN IMMEDIATE');self.err(None,lambda:self.spool.execute(q));self.assertEqual(self.keeper.diagnostics()['leases'],0)
        finally:c.execute('ROLLBACK');c.close()
        lid=self.spool.execute(q);self.assertEqual(self.spool.execute(q),lid)
    def test_actual_sqlite_full_no_receipt(self):
        q=self.prepared('reserve');c=self.keeper.connection
        c.execute('PRAGMA max_page_count='+str(c.execute('PRAGMA page_count').fetchone()[0]))
        # Saturate available space using the real metadata page, rolled back by SQLite.
        failed=False
        for n in range(1,30):
            nonce=h('full-'+str(n));t=self.begin_index(nonce);self.chunks(t,self.bundle.index)
            call=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30),nonce=nonce)
            cmd=self.cmd('reserve',[t,pin_values(self.rpin),30],call=call)
            try:self.spool.execute(cmd)
            except Exception as ex:
                if getattr(ex,'code',None)=='SQLITE_FULL':failed=True;break
                raise
        self.assertTrue(failed,'must observe actual SQLITE_FULL, not unrelated quota error')
    def test_fsync_failure_keeps_no_ack(self):
        t=self.begin_index();q=self.cmd('chunk',[t,0,self.bundle.index])
        with patch('par_keeper_upload.spool.os.fsync',side_effect=OSError(errno.EIO,'synthetic fsync')):self.err('OUTCOME_UNKNOWN',lambda:self.spool.execute(q))
        self.reopen();self.assertEqual(self.spool._meta(t)[0][3],0)
    def test_unlink_failure_keeps_committed_stage(self):
        q=self.prepared('reserve')
        original=Path.unlink
        def unlink(path,*a,**kw):
            if path.suffix=='.part':raise OSError(errno.EIO,'synthetic unlink')
            return original(path,*a,**kw)
        with patch.object(Path,'unlink',unlink):self.err('OUTCOME_UNKNOWN',lambda:self.spool.execute(q))
        self.reopen();lid=self.spool.execute(q);self.assertEqual(self.keeper.diagnostics()['leases'],1);self.assertEqual(len(lid),32)
    def test_no_automatic_stage_gc_after_authority_change(self):
        t=self.begin_index();self.chunks(t,self.bundle.index);self.keeper.update_authority(replace(self.authority,head=h('new'),sequence=2))
        self.reopen();self.assertTrue((self.stage_root/(t.hex()+'.part')).exists());self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0)

BOUNDARIES={
 'begin':['begin.after_part','begin.before_meta','begin.after_replace','begin.after_meta'],
 'chunk':['chunk.after_write','chunk.after_fsync','chunk.before_meta','chunk.after_replace','chunk.after_meta'],
 'reserve':['finalize.before_keeper','reserve.before_commit','reserve.after_commit','finalize.after_keeper','finalize.before_meta','finalize.after_replace','finalize.after_meta','retire.before_unlink','retire.after_unlink','retire.after_sync'],
 'put':['object.synced','put.before_commit','put.after_commit','finalize.after_keeper','finalize.after_meta','retire.after_unlink'],
 'seal':['seal.signed','seal.before_commit','seal.after_commit','seal.ack']}
for action,events in BOUNDARIES.items():
    for event in events:
        def test(self,a=action,e=event):self.crash(a,e)
        name='test_sigkill_'+action+'_'+event.replace('.','_');setattr(UploadFaults,name,test)
