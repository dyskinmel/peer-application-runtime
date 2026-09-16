import json,os,signal,subprocess,sys
from pathlib import Path
from submission_retire_support import RetireTest,h
from par_keeper.contract import authority_body
from par_wire.codec import encode
from par_keeper_service.transport import recover_stale,socket_identity
from par_job_control.controller import Controller
class RetirementRestart(RetireTest):
    def close_all(self):
        self.st.close();self.st=None;self.ctl.close();self.ctl=None;self.host.close();self.host=None;self.window.close();self.window=None;self.keeper.close();self.keeper=None
    def open_all(self,revision=1):
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id);self.start_host()
        self.ctl=Controller(self.host,Path(self.tmp.name)/'controller',self.op,revision)
        self.st=self.rm.RetiringSubmissions(self.ctl,self.sroot,migrate_legacy=True)
    def crash(self,event,operation='retire',registered=False):
        if registered:
            d,r=self.ready();self.st.submit(d)
        else:d,r=self.partial()
        q=self.retire_request(d);revision=1
        if operation=='rebind':
            self.stop_at('submit.retire_intent.after_sync',lambda:self.st.retire(q));self.reopen();self.ctl.replace_controller(self.op,2);revision=2;q=self.retire_request(d)
        elif operation=='reconcile':
            self.st.chunk(d,17,r[17:]);self.stop_at('submit.before_dispatch',lambda:self.st.submit(d));q=self.retire_request(d)
        elif operation=='migration':
            cfg=dict(self.st.config);cfg[0]=1;cfg[1]=self.sc.PROFILE;(self.sroot/'CONFIG.cbor').write_bytes(self.sc.dump(cfg,4096))
        control=self.socket_dir/'retire-worker.sock'
        data={'keeper':str(self.path),'spool':str(self.wroot),'store':self.store_id.hex(),'seed':self.ks.hex(),'authority':encode(authority_body(self.keeper.authority)).hex(),
              'quota':self.total*3,'jobs':str(self.jroot),'journal':str(Path(self.tmp.name)/'controller'),'stage':str(self.sroot),
              'operator':self.op.hex(),'revision':revision,'request':q.hex(),'event':event,'operation':operation,'read':str(self.socket_path),'upload':str(self.upload_path),'control':str(control)}
        cfg=Path(self.tmp.name)/'retire-worker.json';cfg.write_text(json.dumps(data));cfg.chmod(0o600);self.close_all()
        p=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('submission_retire_crash_worker.py')),str(cfg)],capture_output=True,timeout=25,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(p.returncode,-signal.SIGKILL,p.stderr.decode());self.assertEqual(json.loads(p.stdout),{'hit':event,'pgid':os.getpgid(0)})
        for path in (self.socket_path,self.upload_path,control):recover_stale(path,socket_identity(path))
        self.open_all(revision)
        self.assertIsNone(self.host.selected);self.assertEqual(self.window.phase,'OPEN')
        if operation=='rebind':self.st.rebind(q)
        elif operation=='reconcile':
            if self.st.progress(d)['state']=='INFLIGHT':self.st.reconcile_registration(q)
            q=self.retire_request(d)
        v=self.st.retire(q);self.assertEqual(v['state'],'TOMBSTONED');self.assertEqual(self.st.diagnostics()['reserved_payload_bytes'],0)
        self.assertFalse(self.st.payload_path(self.jid()).exists());self.assertEqual(self.st.retire(q),v)
        self.assertEqual(len(self.host.jobs.list()),int(registered))
        if registered:self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED')

BOUNDARIES=[
 ('submit.retire_intent.before_fsync','retire'),('submit.retire_intent.before_replace','retire'),
 ('submit.retire_intent.after_replace','retire'),('submit.retire_intent.after_sync','retire'),
 ('submit.retire.before_unlink','retire'),('submit.retire.after_unlink','retire'),('submit.retire.after_payload_sync','retire'),
 ('submit.retire_removed.before_replace','retire'),('submit.retire_removed.after_replace','retire'),('submit.retire_removed.after_sync','retire'),
 ('submit.retire.before_release','retire'),('submit.retire_tombstone.before_replace','retire'),
 ('submit.retire_tombstone.after_replace','retire'),('submit.retire_tombstone.after_sync','retire'),
 ('submit.retire_rebind.before_replace','rebind'),('submit.retire_rebind.after_replace','rebind'),('submit.retire_rebind.after_sync','rebind'),
 ('submit.retire_reconciled.before_replace','reconcile'),('submit.retire_reconciled.after_sync','reconcile'),
 ('submit.retire_migration.before_replace','migration'),('submit.retire_migration.after_replace','migration'),('submit.retire_migration.after_sync','migration')]
for event,op in BOUNDARIES:
    def case(self,e=event,o=op):self.crash(e,o)
    setattr(RetirementRestart,'test_sigkill_'+event.replace('.','_'),case)
for event in ('submit.retire.after_unlink','submit.retire_tombstone.after_sync'):
    def case(self,e=event):self.crash(e,registered=True)
    setattr(RetirementRestart,'test_sigkill_registered_'+event.replace('.','_'),case)
