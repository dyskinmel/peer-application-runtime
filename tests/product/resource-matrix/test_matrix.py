import asyncio,importlib,importlib.util,unittest
class MatrixTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.assertIsNotNone(importlib.util.find_spec('tools.run_resource_matrix'),'real owner matrix runner missing')
  self.m=importlib.import_module('tools.run_resource_matrix')
 async def test_two_peers_two_slots(self):
  r=await self.m.run_cell(2,2,rounds_per_peer=2)
  self.assertEqual(r['status'],'PASS',r);self.assertEqual(r['child_exit_codes'],[0,0]);self.assertTrue(r['other_progress_before_slow_cancel']);self.assertEqual(r['peak_active'],2);self.assertTrue(r['readonly_unchanged']);self.assertEqual(len(set(r['owner_pids'])),2)
 async def test_eight_peers_four_slots(self):
  r=await self.m.run_cell(8,4,rounds_per_peer=2)
  self.assertEqual(r['status'],'PASS',r);self.assertEqual(len(r['owner_pids']),8);self.assertEqual(r['peak_active'],4);self.assertEqual(r['completed_jobs'],16);self.assertEqual(r['queue_full_rejections'],1)
 async def test_one_slot_status_cancel_remain_available(self):
  r=await self.m.run_cell(2,1,rounds_per_peer=2)
  self.assertEqual(r['status'],'PASS',r);self.assertFalse(r['other_progress_before_slow_cancel']);self.assertTrue(r['control_bypasses_queue']);self.assertEqual(r['peak_active'],1)
 async def test_real_fd_leak_is_detected(self):
  r=await self.m.run_cell(2,2,rounds_per_peer=1,inject='fd')
  self.assertEqual(r['status'],'FAIL');self.assertIn('DRIVER_FD_GROWTH',r['violations'])
 async def test_real_task_leak_is_detected(self):
  r=await self.m.run_cell(2,2,rounds_per_peer=1,inject='task')
  self.assertEqual(r['status'],'FAIL');self.assertIn('DRIVER_TASK_GROWTH',r['violations'])
 async def test_matrix_campaign_sealed_boundary_resume(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp)/'matrix';cells=[{'participants':2,'max_active':1,'rounds_per_peer':1},{'participants':2,'max_active':2,'rounds_per_peer':1}]
   r=await self.m.run_campaign(root,cells=cells,stop_after=1);self.assertEqual(r['result'],'PARTIAL',r)
   r=await self.m.run_campaign(root,cells=cells,resume=True);self.assertEqual(r['result'],'PASS',r);self.assertEqual([x['round']for x in r['cells']],[0,1])
   self.assertTrue(all(x['child_exit_codes']==[0,0]for x in r['cells']))
