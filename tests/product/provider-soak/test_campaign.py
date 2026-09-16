"""Campaign integrity and no-success-by-retry tests; real local files."""
import importlib,json,os,tempfile,unittest
from pathlib import Path
class CampaignTests(unittest.TestCase):
 def setUp(self):
  self.mod=importlib.import_module('product.wp13.par_soak')
  self.assertTrue(hasattr(self.mod,'Campaign'),'WP13 Campaign implementation missing')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'campaign'
  self.binding={'source':'a'*64,'environment':'b'*64}
  self.config={'rounds':14,'seed':5400}
  self.c=self.mod.Campaign.create(self.root,self.binding,self.config);self.addCleanup(self.c.close)
 def payload(self,i=0):return {'round':i,'metrics':{'fd':7},'status':'PASS'}
 def cycle(self):
  n=self.c.state()['next_round'];self.c.begin(n);self.c.finish(n,self.payload(n));return n
 def test_initial_state_is_not_pass(self):self.assertEqual(self.c.state()['result'],'PARTIAL');self.assertEqual(self.c.state()['completed'],0)
 def test_schedule_is_seeded_and_balanced(self):
  a=[self.c.scenario(i)for i in range(14)];self.assertEqual(len(set(a)),7)
  for x in set(a):self.assertEqual(a.count(x),2)
 def test_finish_requires_begin(self):
  with self.assertRaisesRegex(Exception,'NO_ACTIVE'):self.c.finish(0,self.payload())
 def test_begin_wrong_index_rejected(self):
  with self.assertRaisesRegex(Exception,'ROUND_ORDER'):self.c.begin(1)
 def test_duplicate_begin_rejected(self):
  self.c.begin(0)
  with self.assertRaisesRegex(Exception,'ACTIVE'):self.c.begin(0)
 def test_wrong_result_round_rejected(self):
  self.c.begin(0)
  with self.assertRaisesRegex(Exception,'ROUND_ORDER'):self.c.finish(1,self.payload(1))
 def test_duplicate_finish_rejected(self):
  self.cycle()
  with self.assertRaisesRegex(Exception,'NO_ACTIVE'):self.c.finish(0,self.payload())
 def test_fail_terminal_no_retry(self):
  self.c.begin(0);self.c.finish(0,{'round':0,'status':'FAIL','reason':'FD_LEAK'})
  self.assertEqual(self.c.state()['result'],'FAIL')
  with self.assertRaisesRegex(Exception,'FAILED'):self.c.begin(1)
 def test_failure_survives_reopen(self):
  self.c.begin(0);self.c.finish(0,{'round':0,'status':'FAIL','reason':'TEST'});self.c.close()
  with self.mod.Campaign.open(self.root,self.binding,self.config)as c:
   self.assertEqual(c.state()['result'],'FAIL')
   with self.assertRaisesRegex(Exception,'FAILED'):c.begin(1)
 def test_boundary_resume_retains_prior_rounds(self):
  self.cycle();self.c.seal();pin=self.c.pin();self.c.close()
  with self.mod.Campaign.open(self.root,self.binding,self.config,pin=pin)as c:
   self.assertEqual(c.state()['completed'],1);self.assertEqual(c.state()['next_round'],1);c.begin(1);c.finish(1,self.payload(1))
 def test_pending_begin_is_not_replayed(self):
  self.c.begin(0);self.c.close()
  with self.mod.Campaign.open(self.root,self.binding,self.config)as c:
   self.assertEqual(c.state()['result'],'INTERRUPTED')
   with self.assertRaisesRegex(Exception,'ACTIVE'):c.begin(0)
 def test_completion_requires_every_identity(self):
  for _ in range(14):self.cycle()
  self.c.seal();self.assertEqual(self.c.state()['result'],'PASS')
  with self.assertRaisesRegex(Exception,'COMPLETE'):self.c.begin(14)
 def test_changed_source_rejected(self):
  self.c.close()
  with self.assertRaisesRegex(Exception,'BINDING'):self.mod.Campaign.open(self.root,{**self.binding,'source':'c'*64},self.config)
 def test_changed_toolchain_rejected(self):
  self.c.close()
  with self.assertRaisesRegex(Exception,'BINDING'):self.mod.Campaign.open(self.root,{**self.binding,'environment':'c'*64},self.config)
 def test_changed_seed_rejected(self):
  self.c.close()
  with self.assertRaisesRegex(Exception,'BINDING'):self.mod.Campaign.open(self.root,self.binding,{**self.config,'seed':1})
 def test_lock_refuses_second_writer(self):
  with self.assertRaisesRegex(Exception,'LOCKED'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_create_existing_rejected(self):
  with self.assertRaises((FileExistsError,ValueError)):self.mod.Campaign.create(self.root,self.binding,self.config)
 def test_tampered_event_rejected(self):
  self.cycle();self.c.close();p=self.root/'000001.json';r=json.loads(p.read_text());r['payload']['round']=8;p.write_text(json.dumps(r))
  with self.assertRaisesRegex(Exception,'CORRUPT'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_missing_event_rejected(self):
  self.cycle();self.c.close();(self.root/'000001.json').unlink()
  with self.assertRaisesRegex(Exception,'CORRUPT'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_known_tail_rollback_rejected(self):
  self.cycle();pin=self.c.pin();self.c.close();(self.root/'000002.json').unlink()
  with self.assertRaisesRegex(Exception,'PIN'):self.mod.Campaign.open(self.root,self.binding,self.config,pin=pin)
 def test_partial_event_rejected(self):
  self.c.close();p=self.root/'000001.json';p.write_text('{');p.chmod(0o600)
  with self.assertRaisesRegex(Exception,'CORRUPT'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_symlink_event_rejected(self):
  self.cycle();self.c.close();p=self.root/'000001.json';q=self.root.parent/'other';p.rename(q);p.symlink_to(q)
  with self.assertRaisesRegex(Exception,'UNSAFE'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_world_readable_root_rejected(self):
  self.c.close();self.root.chmod(0o755)
  with self.assertRaisesRegex(Exception,'UNSAFE'):self.mod.Campaign.open(self.root,self.binding,self.config)
 def test_nan_metric_rejected(self):
  self.c.begin(0)
  with self.assertRaises(ValueError):self.c.finish(0,{'round':0,'status':'PASS','rss':float('nan')})
 def test_bool_rounds_rejected(self):
  with self.assertRaises(ValueError):self.mod.Campaign.create(self.root.parent/'bad',self.binding,{'rounds':True,'seed':1})
 def test_zero_and_unbounded_rounds_rejected(self):
  for n in (0,257):
   with self.assertRaises(ValueError):self.mod.Campaign.create(self.root.parent/str(n),self.binding,{'rounds':n,'seed':1})
 def test_large_payload_rejected(self):
  self.c.begin(0)
  with self.assertRaisesRegex(Exception,'BUDGET'):self.c.finish(0,{'round':0,'status':'PASS','text':'x'*140000})
 def test_closed_handle_rejected(self):
  self.c.close()
  with self.assertRaisesRegex(Exception,'CLOSED'):self.c.begin(0)
 def test_all_rounds_without_process_finalization_not_pass(self):
  for _ in range(14):self.cycle()
  self.assertNotEqual(self.c.state()['result'],'PASS','child shutdown still unconfirmed')
 def test_finalization_failure_not_overwritten_by_reopen(self):
  self.assertTrue(hasattr(self.c,'abort'),'campaign finalization failure recorder missing')
  self.cycle();self.c.abort('CHILD_EXIT_NONZERO');self.c.close()
  with self.mod.Campaign.open(self.root,self.binding,self.config)as c:self.assertEqual(c.state()['result'],'FAIL')
 def killed_child(self,finish=False):
  import subprocess,signal,sys
  self.c.close();other=self.root.parent/'crashed'
  code="import os,signal,sys;sys.path.insert(0,sys.argv[1]);from product.wp13.par_soak import Campaign;c=Campaign.create(sys.argv[2],{'source':'a'*64,'environment':'b'*64},{'rounds':14,'seed':5400});c.begin(0);"+("c.finish(0,{'round':0,'status':'PASS'});"if finish else'')+"os.kill(os.getpid(),signal.SIGKILL)"
  r=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(Path(__file__).resolve().parents[3]),str(other)],capture_output=True,timeout=10)
  self.assertEqual(r.returncode,-signal.SIGKILL,r.stderr);return other
 def test_sigkill_after_begin_releases_lock_but_does_not_replay(self):
  other=self.killed_child()
  with self.mod.Campaign.open(other,self.binding,self.config)as c:
   self.assertEqual(c.state()['result'],'INTERRUPTED')
   with self.assertRaisesRegex(Exception,'ACTIVE'):c.begin(0)
 def test_sigkill_after_result_requires_finalization_not_auto_pass(self):
  other=self.killed_child(True)
  with self.mod.Campaign.open(other,self.binding,self.config)as c:
   self.assertEqual(c.state()['result'],'UNSEALED')
   with self.assertRaisesRegex(Exception,'FINALIZATION'):c.begin(1)
 def test_summary_file_cannot_promote_unfinished_campaign(self):
  self.c.begin(0);self.c.close();(self.root.parent/'campaign-summary.json').write_text('{"result":"PASS"}')
  with self.mod.Campaign.open(self.root,self.binding,self.config)as c:self.assertEqual(c.state()['result'],'INTERRUPTED')
