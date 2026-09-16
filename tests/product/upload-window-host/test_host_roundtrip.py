from host_process_support import *

class HostRoundtrip(ProcessTest):
    def test_roundtrip_upload_and_read(self):
        self.start_host();lid,rc=self.send_bundle();self.assertEqual(self.client.receipt(lid),rc)
        for oid,raw in self.bundle.objects.items():self.assertEqual(self.remote().fetch(oid),raw)
    def test_retry_same_bundle_same_lease_receipt(self):
        self.start_host();first=self.send_bundle();self.assertEqual(self.send_bundle(),first)
    def test_next_window_rejects_old_client_and_request(self):
        self.start_host();old=self.uclient;oldq=old.command('progress',h('operation'),h('token'));self.stop_process()
        rec=self.close_offline();self.open_next_offline(rec);self.start_host()
        self.err('WINDOW_SCOPE',lambda:old.execute(oldq));self.send_bundle()
    def test_retire_close_compact_next_generation(self):
        self.start_host();q=self.uclient.command('begin',h('begin'),['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()])
        self.beginraw=self.w.check_command(self.p,self.grant,q)[4];t=self.uclient.execute(q)[0];self.uclient.chunk(t,0,self.bundle.index[:20]);self.stop_process()
        request=self.retirement_request(authority=self.authority);wrapped=self.wrap(request,'retire')
        self.admin('retire',wrapped);self.assertFalse(self.live(t,'.part').exists())
        rec=self.close_offline();self.assertFalse(self.live(t).exists());self.open_next_offline(rec);self.start_host();self.send_bundle()
    def test_uploaded_handoff_compacts_and_next_generation_uses_new_ids(self):
        self.start_host();oldlid,_=self.send_bundle();self.stop_process();rec=self.close_offline();self.open_next_offline(rec);self.start_host()
        newlid,_=self.send_bundle();self.assertNotEqual(newlid,oldlid);self.assertEqual(self.client.status(oldlid)['generation'],1)
    def test_separate_donor_keeper_recipient_after_rollover(self):
        self.start_host();self.stop_process();self.open_next_offline(self.close_offline());self.start_host()
        job=Path(self.tmp.name)/'donor.json';job.write_text(json.dumps({'socket':str(self.upload_path),'keeper':self.kp.hex(),'seed':self.cs.hex(),'cap':self.cap.hex(),'store':self.store_id.hex(),'window':self.grant.hex(),'index':self.bundle.index.hex(),'pin':pr.dump(pin_values(self.rpin),65536).hex(),'objects':{k.hex():v.hex() for k,v in self.bundle.objects.items()}}));job.chmod(0o600)
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('host_donor_worker.py')),str(job)],capture_output=True,timeout=25,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,0,cp.stderr.decode());self.lid=bytes.fromhex(json.loads(cp.stdout)['lease']);job.unlink()
        expected=self.remove_donor();r=self.run_receiver(self.job());self.assertEqual(r['sha256'],expected);self.assertFalse(r['status']['writable'])
