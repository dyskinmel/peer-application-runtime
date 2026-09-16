import hashlib,json,os,select,shutil,signal,subprocess,sys
from pathlib import Path
from dataclasses import replace
from service_support import ServiceTest,h,ROOT
from par_keeper import issue_capability
from par_keeper.contract import pin_values
from par_recovery import Inbox
from par_wire.codec import encode

class ServiceRecovery(ServiceTest):
    def remote(self):return self.ipc.RemoteProvider(self.client,self.lid,self.bundle.index,self.rpin)
    def job(self):
        out=Path(self.tmp.name);f=out/'recipient-job.json'
        j={'socket':str(self.socket_path),'keeper':self.kp.hex(),'subject_seed':self.cs.hex(),'capability':self.cap.hex(),'lease':self.lid.hex(),
            'index':self.bundle.index.hex(),'pin':encode(pin_values(self.rpin)).hex(),'recipient_secret':self.reader['secret'].hex(),
            'inbox':str(out/'recipient-inbox'),'destination':str(out/'recipient-output'),'output':str(out/'recovered-file')}
        f.write_text(json.dumps(j));f.chmod(0o600);return f
    def remove_donor(self):
        expected=hashlib.sha256(self.source.read_bytes()).hexdigest();root=self.db._storage.root
        self.db.close();shutil.rmtree(root);self.source.unlink();self.assertFalse(root.exists());return expected
    def run_receiver(self,job):
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('receiver_worker.py')),str(job)],capture_output=True,timeout=12,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,0,cp.stderr.decode());return json.loads(cp.stdout)
    def test_separate_recipient_after_donor_removed(self):
        self.start_process();job=self.job();expected=self.remove_donor();r=self.run_receiver(job)
        self.assertEqual(r['sha256'],expected);self.assertFalse(r['status']['writable']);self.assertFalse(r['status']['applied']);self.assertFalse(r['status']['inner_validated'])
    def test_sigkill_recipient_after_ack_reuses_received_objects(self):
        self.start_process();job=self.job();expected=self.remove_donor()
        child=subprocess.Popen([sys.executable,'-I','-S',str(Path(__file__).with_name('receiver_worker.py')),str(job),'partial'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            self.assertTrue(select.select([child.stdout],[],[],10)[0]);first=child.stdout.readline();self.assertTrue(first,child.stderr.read().decode() if child.poll() is not None else 'no marker');v=json.loads(first)
            self.assertEqual(v['state'],'PARTIAL_PERSISTED');self.assertEqual(len(v['fetched']),1)
            child.kill();child.wait(timeout=5);self.assertEqual(child.returncode,-signal.SIGKILL)
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.stdout.close();child.stderr.close()
        r=self.run_receiver(job);self.assertEqual(r['sha256'],expected)
        self.assertEqual(r['before_missing'],len(self.bundle.objects)-1);self.assertNotIn(v['fetched'][0],r['fetched']);self.assertEqual(len(r['fetched']),len(set(r['fetched'])))
    def test_keeper_restart_during_partial_receive(self):
        self.start_process();remote=self.remote();path=Path(self.tmp.name)/'inbox'
        with Inbox(path,self.bundle.index,self.rpin) as rx:rx.pull(remote,limit=2);before=set(rx.missing())
        self.stop_process();self.start_process(existing=True)
        with Inbox(path,self.bundle.index,self.rpin) as rx:
            self.assertEqual(set(rx.missing()),before)
            while rx.missing():rx.pull(self.remote(),limit=8)
            v=rx.finalize(Path(self.tmp.name)/'done',self.p,self.reader['secret'])
        self.assertFalse(v.status()['writable'])
    def test_remote_provider_rejects_unknown_object_before_request(self):
        self.start_process();self.err('OBJECT_SCOPE',lambda:self.remote().fetch(h('not-in-index')))
    def test_remote_provider_rejects_wrong_pin(self):
        self.start_process();self.err('PIN_MISMATCH',lambda:self.ipc.RemoteProvider(self.client,self.lid,self.bundle.index,replace(self.rpin,index_id=h('bad'))))
    def test_missing_object_blocks_recovery(self):
        self.lid,_=self.ready();oid=sorted(self.bundle.objects)[0];self.damage(self.lid,'missing',oid);self.start_process(existing=True)
        with Inbox(Path(self.tmp.name)/'rx',self.bundle.index,self.rpin) as rx:
            self.err(None,lambda:rx.pull(self.remote(),limit=32));self.assertTrue(rx.missing())
    def test_corrupt_object_blocks_recovery(self):
        self.lid,_=self.ready();oid=sorted(self.bundle.objects)[0];self.damage(self.lid,'corrupt',oid);self.start_process(existing=True)
        self.err('REMOTE_DATA_INVALID',lambda:self.remote().fetch(oid))
    def test_repaired_keeper_serves_only_valid_replacement(self):
        self.lid,_=self.ready();oid=sorted(self.bundle.objects)[0];self.damage(self.lid,'corrupt',oid)
        req=self.repair_request(self.lid,[oid]);self.repair(self.lid,req);self.start_process(existing=True)
        self.assertEqual(self.remote().fetch(oid),self.bundle.objects[oid])
    def test_authority_updated_between_restarts_invalidates_old_client(self):
        self.start_process();self.stop_process();self.open_keeper();new=replace(self.authority,head=h('next'),sequence=2)
        self.keeper.update_authority(new);self.authority=new;self.start_process(existing=True)
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.client.status(self.lid))
    def test_fresh_capability_after_known_authority_update(self):
        self.start_process();self.stop_process();self.open_keeper();new=replace(self.authority,head=h('next'),sequence=2)
        self.keeper.update_authority(new);self.authority=new
        self.cap=issue_capability(self.p,self.s.owner,new,self.kp,self.cp,self.rpin.index_id,('get','status','receipt','challenge'),60,h('newcap'))
        self.start_process(existing=True);self.assertFalse(self.client.status(self.lid)['product_qualified'])
    def test_released_keeper_does_not_serve_to_reconnecting_client(self):
        self.start_process();self.stop_process();self.open_keeper();self.release(self.lid);self.start_process(existing=True)
        self.err('REMOTE_UNAVAILABLE',lambda:self.remote().fetch(sorted(self.bundle.objects)[0]))
    def test_reclaimed_keeper_does_not_serve_removed_data(self):
        self.lid,_=self.ready();self.release(self.lid);req=self.gc_request(self.lid);self.gc(self.lid,req);self.start_process(existing=True)
        self.err('REMOTE_UNAVAILABLE',lambda:self.remote().fetch(sorted(self.bundle.objects)[0]));self.assertEqual(self.client.status(self.lid)['state'],'RECLAIMED')
