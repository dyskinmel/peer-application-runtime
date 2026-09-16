"""A real scheduled host subprocess serving both existing protocol clients."""
import json,sys,time,subprocess
from pathlib import Path
from host_process_support import ProcessTest,h,ROOT
from par_management_jobs import ManagementJobs
class SchedulerHostProcess(ProcessTest):
    def setUp(self):
        super().setUp();self.job_root=Path(self.tmp.name)/'live-jobs';self.run_job=False
        self.assertTrue((ROOT/'tools/keeper_scheduled_host.py').is_file(),'Scheduled host CLI not implemented')
    def host_args(self):
        args=super().host_args();args[args.index(str(ROOT/'tools/keeper_window_host.py'))]=str(ROOT/'tools/keeper_scheduled_host.py')
        args+=['--jobs',str(self.job_root)]
        if self.run_job:args+=['--run-job',h('host-close').hex()]
        return args
    def queued_close(self):
        a,q=self.proposed()
        with ManagementJobs(self.window,self.job_root) as jobs:jobs.submit(h('host-close'),action='close',command=q,archive=a)
    def test_unselected_job_does_not_run_in_live_host(self):
        self.queued_close();self.start_host();self.send_bundle();self.stop_process();self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id)
        with ManagementJobs(self.window,self.job_root) as jobs:self.assertEqual(jobs.poll(h('host-close'))['state'],'QUEUED')
    def test_explicit_selected_job_closes_without_host_restart(self):
        self.queued_close();self.run_job=True;self.start_host()
        # Existing generation client must observe the closed phase, never auto-open.
        for _ in range(100):
            try:self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('try'))
            except Exception as e:
                if getattr(e,'code','')=='WINDOW_CLOSED':break
            time.sleep(.01)
        else:self.fail('closed generation was not observed')
        self.stop_process();self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id)
        with ManagementJobs(self.window,self.job_root) as jobs:self.assertEqual(jobs.poll(h('host-close'))['state'],'SUCCEEDED')
    def test_real_upload_and_read_remain_compatible(self):
        self.start_host();lid,receipt=self.send_bundle();oid=sorted(self.bundle.objects)[0]
        self.assertEqual(self.client.fetch(lid,oid),self.bundle.objects[oid]);self.assertEqual(self.client.receipt(lid),receipt)
    def test_provider_removed_donor_receiver_restores(self):
        self.start_host();lid,receipt=self.send_bundle();job=self.job();expected=self.remove_donor();result=self.run_receiver(job)
        self.assertEqual(result['sha256'],expected);self.assertFalse(result['status']['writable']);self.assertFalse(result['status']['applied'])
    def test_host_cli_has_no_generic_management_method(self):
        cp=subprocess.run([sys.executable,str(ROOT/'tools/keeper_scheduled_host.py'),'--help'],capture_output=True,timeout=5)
        self.assertEqual(cp.returncode,0);self.assertIn(b'--run-job',cp.stdout);self.assertNotIn(b'--eval',cp.stdout);self.assertNotIn(b'--method',cp.stdout)
