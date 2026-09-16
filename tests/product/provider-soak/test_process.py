"""Actual persistent Node/Python processes; public synthetic setup, no real CRDT."""
import importlib,tempfile,unittest
from pathlib import Path
class SoakProcessTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.r=importlib.import_module('tools.run_provider_soak')
  self.assertTrue(hasattr(self.r,'run_campaign'),'persistent-process soak runner missing')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'run'
 async def test_every_scenario_in_same_two_processes(self):
  r=await self.r.run_campaign(self.path,rounds=14,seed=54)
  self.assertEqual(r['result'],'PASS');self.assertEqual(r['completed'],14)
  self.assertEqual(len(r['segments']),1);self.assertEqual(r['segments'][0]['rounds'],14)
  self.assertEqual(len(r['scenarios']),7);self.assertTrue(r['persistent_data_unchanged'])
  self.assertIn('memory_total_bytes',r['environment'],'host memory metadata missing');self.assertGreater(r['environment']['memory_total_bytes'],0);self.assertIn('cpu_model',r['environment'])
  self.assertGreater(r['segments'][0]['elapsed_us'],0);self.assertGreater(r['segments'][0]['started_unix_ns'],0)
  self.assertTrue(r['persistent_data_digests_verified'])
 async def test_stop_boundary_resumes_without_repeating_identity(self):
  a=await self.r.run_campaign(self.path,rounds=14,seed=54,stop_after=3)
  self.assertEqual(a['result'],'PARTIAL');self.assertEqual(a['completed'],3)
  b=await self.r.run_campaign(self.path,rounds=14,seed=54,resume=True)
  self.assertEqual(b['result'],'PASS');self.assertEqual(b['completed'],14)
  self.assertEqual([s['rounds']for s in b['segments']],[3,11]);self.assertEqual(len(b['round_ids']),len(set(b['round_ids'])))
 async def test_real_fd_leak_stops_and_is_not_retried(self):
  a=await self.r.run_campaign(self.path,rounds=7,seed=54,inject_fd_leak=0)
  self.assertEqual(a['result'],'FAIL');self.assertEqual(a['first_failure']['round'],0)
  b=await self.r.run_campaign(self.path,rounds=7,seed=54,resume=True)
  self.assertEqual(b['result'],'FAIL');self.assertEqual(b['completed'],0)
 async def test_actual_task_leak_stops(self):
  r=await self.r.run_campaign(self.path,rounds=7,seed=54,inject_task_leak=0)
  self.assertEqual(r['result'],'FAIL');self.assertIn('PYTHON_TASK_GROWTH',r['first_failure']['violations'])
 async def test_fixture_namespace_removed_after_children_exit(self):
  from tools import check_application_owner
  from test_application_process import ApplicationProcessTests
  from unittest.mock import patch
  paths=[];setup=ApplicationProcessTests.asyncSetUp
  async def capture(f):
   await setup(f);paths.append(f.f.root.parent)
  with patch.object(ApplicationProcessTests,'asyncSetUp',capture):
   await self.r.run_campaign(self.path,rounds=1,seed=54)
  self.assertTrue(paths);self.assertFalse(any(p.exists()for p in paths),'campaign fixture directory leaked')
