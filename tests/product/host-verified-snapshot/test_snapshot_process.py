import json, os, select, signal, socket, subprocess, sys
from pathlib import Path
from host_process_support import ProcessTest,h,pr,ROOT

class SnapshotProcess(ProcessTest):
    def setUp(self):
        super().setUp();self.assertTrue((ROOT/'tools/keeper_verified_host.py').is_file(),'verified host CLI is not implemented')
    def host_args(self):
        args=super().host_args();args[3]=str(ROOT/'tools/keeper_verified_host.py');return args+['--verification-mode','signatures']
    def summary(self):
        rc,out,err=self.stop_process();self.assertEqual(rc,0,err);return json.loads(out.strip().splitlines()[-1])
    def test_cold_startup_then_warm_upload(self):
        self.start_host();self.send_bundle();s=self.summary();self.assertEqual(s['startup_verification']['hits'],0)
        self.assertEqual(s['startup_verification']['entries'],0);self.assertGreater(s['startup_verification']['backend_calls'],0)
        self.assertGreater(s['verification']['hits'],0)
    def test_full_mode_has_no_hits(self):
        original=self.host_args;self.host_args=lambda:original()[:-1]+['full'];self.start_host();self.send_bundle();s=self.summary();self.assertEqual(s['verification']['hits'],0)
    def test_warm_retry_same_bundle(self):
        self.start_host();one=self.send_bundle();two=self.send_bundle();self.assertEqual(one,two);self.assertGreater(self.summary()['verification']['hits'],0)
    def test_sigkill_warm_cache_reopens_cold(self):
        self.start_host();t,_=self.uclient.begin('index',self.rpin.index_id,self.bundle.index,h('idx'));self.uclient.chunk(t,0,self.bundle.index[:20]);self.uclient.progress(t)
        ids={p:self.ipc.socket_identity(p) for p in (self.socket_path,self.upload_path)}
        self.assertEqual(self.stop_process(kill=True)[0],-signal.SIGKILL);self.recover_sockets(ids);self.start_host();self.assertEqual(self.uclient.progress(t)[1],20)
        s=self.summary();self.assertEqual(s['startup_verification']['hits'],0)
    def test_closed_window_still_rejected(self):
        self.start_host();old=self.uclient;oldq=old.command('progress',h('op'),h('token'));self.stop_process();rec=self.close_offline();self.open_next_offline(rec);self.start_host()
        self.err('WINDOW_SCOPE',lambda:old.execute(oldq));self.send_bundle()
    def test_read_receipt_unchanged(self):
        self.start_host();lid,rc=self.send_bundle();self.assertEqual(self.client.receipt(lid),rc)
    def test_provider_pinned_failure_no_fallback(self):
        cp=subprocess.run(self.host_args(),input=h('wrong'),capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertIn(b'KEEPER_IDENTITY',cp.stderr)
    def test_invalid_cache_budget_before_opening(self):
        cp=subprocess.run(self.host_args()+['--cache-max-entries','0'],input=self.ks,capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertIn(b'CACHE_CONFIG',cp.stderr);self.assertFalse(self.upload_path.exists())
