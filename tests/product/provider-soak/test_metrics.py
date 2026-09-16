import asyncio,importlib,os,socket,unittest
class MetricsTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.m=importlib.import_module('product.wp13.par_soak')
  self.assertTrue(hasattr(self.m,'sample_python'),'resource sampler missing')
 def pair(self):
  return ({'pid':77,'segment':'s','fd':8,'tasks':1,'rss_bytes':1000,'channels':0,'inflight':0},
          {'pid':78,'segment':'s','fd':9,'active':{'PipeWrap':3},'rss_bytes':1000,'pendingStore':0,'pendingRequests':0,'inflight':0})
 async def test_python_metrics_are_measured(self):
  r=self.m.sample_python([]);self.assertEqual(r['pid'],os.getpid());self.assertGreater(r['fd'],0);self.assertGreater(r['tasks'],0);self.assertGreater(r['rss_bytes'],0)
 async def test_reserved_descriptors_accounted_separately(self):
  a,b=socket.socketpair()
  try:
   r=self.m.sample_python([a.fileno(),b.fileno()]);self.assertEqual(r['raw_fd']-r['fd'],2);self.assertEqual(r['reserved_fd'],2)
  finally:a.close();b.close()
 async def test_missing_reserved_descriptor_is_not_subtracted(self):
  with self.assertRaisesRegex(Exception,'RESERVED'):self.m.sample_python([999999])
 async def test_baseline_no_growth_is_pass(self):
  a,b=self.pair();self.assertEqual(self.m.compare_resources(a,b,a,b),[])
 async def test_fd_growth_is_detected(self):
  a,b=self.pair();self.assertIn('PYTHON_FD_GROWTH',self.m.compare_resources(a,b,{**a,'fd':9},b))
 async def test_task_growth_is_detected(self):
  a,b=self.pair();self.assertIn('PYTHON_TASK_GROWTH',self.m.compare_resources(a,b,{**a,'tasks':2},b))
 async def test_node_live_handle_growth_detected(self):
  a,b=self.pair();self.assertIn('NODE_ACTIVE_GROWTH',self.m.compare_resources(a,b,a,{**b,'active':{'PipeWrap':4}}))
 async def test_child_restart_requires_new_baseline(self):
  a,b=self.pair()
  with self.assertRaisesRegex(Exception,'SEGMENT'):self.m.compare_resources(a,b,{**a,'pid':99},b)
 async def test_rss_is_bounded_diagnostic_not_ignored(self):
  a,b=self.pair();self.assertIn('NODE_RSS_BUDGET',self.m.compare_resources(a,b,a,{**b,'rss_bytes':1000+65*1024**2}))
 async def test_pending_cleanup_is_not_pass(self):
  a,b=self.pair();self.assertIn('NODE_PENDING',self.m.compare_resources(a,b,a,{**b,'pendingRequests':1}))
 async def test_missing_counter_not_zero(self):
  a,b=self.pair();v=dict(a);del v['fd']
  with self.assertRaisesRegex(Exception,'METRIC'):self.m.compare_resources(a,b,v,b)
 async def test_negative_boolean_nan_counter_rejected(self):
  a,b=self.pair()
  for n in (-1,True,float('nan')):
   with self.assertRaisesRegex(Exception,'METRIC'):self.m.compare_resources(a,b,{**a,'fd':n},b)
