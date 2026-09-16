import asyncio,importlib,importlib.util,socket,unittest

class FactoryTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.assertIsNotNone(importlib.util.find_spec('product.wp13.par_matrix.factory'),'factory conformance missing')
  self.m=importlib.import_module('product.wp13.par_matrix.factory');self.checks=[];self.opened=[]
 def check(self,factory=None,probe=None):
  c=self.m.FactoryCheck(factory,'a',probe or self.probe);self.checks.append(c);return c
 async def factory(self,peer,cancel):
  if cancel.is_set():raise self.m.FactoryRefusal('CANCELLED')
  a,b=socket.socketpair()
  class C:
   async def close(s):s.closed+=1;a.close();b.close()
  c=C();c.peer=peer;c.closed=0;c.a=a;c.b=b;self.opened.append(c);return c
 async def probe(self,c):
  c.a.send(b'x');return c.b.recv(1)==b'x'
 async def asyncTearDown(self):
  for c in getattr(self,'checks',[]):await c.finish(timeout=1)
  for c in getattr(self,'opened',[]):c.a.close();c.b.close()
 async def test_real_private_socket_contract(self):
  r=await self.check(self.factory).run();self.assertEqual(r['result'],'PASS');self.assertTrue(r['cleanup_complete']);self.assertEqual(len(r['checks']),5);self.assertTrue(all(c.closed==1 for c in self.opened))
 async def test_missing_provider_blocked_zero(self):
  r=await self.check().run();self.assertEqual(r['result'],'BLOCKED');self.assertEqual(r['checks'],[])
 async def test_duplicate_connection_rejected_single_close(self):
  c=await self.factory('a',asyncio.Event())
  async def bad(peer,cancel):return c
  r=await self.check(bad).run();self.assertEqual(r['result'],'FAIL');self.assertIn('DUPLICATE_CONNECTION',r['reason']);self.assertEqual(c.closed,1)
 async def test_explicit_busy_is_allowed_not_offline(self):
  current=None
  async def one(peer,cancel):
   nonlocal current
   if cancel.is_set():raise self.m.FactoryRefusal('CANCELLED')
   if current and current.closed==0:raise self.m.FactoryRefusal('BUSY')
   current=await self.factory(peer,cancel);return current
  r=await self.check(one).run();self.assertEqual(r['result'],'PASS');self.assertIn('exclusive_or_distinct',r['checks'])
 async def test_offline_not_successful_busy(self):
  n=0
  async def f(peer,cancel):
   nonlocal n;n+=1
   if n==2:raise OSError('offline')
   return await self.factory(peer,cancel)
  r=await self.check(f).run();self.assertEqual(r['result'],'FAIL');self.assertEqual(len(self.opened),1);self.assertEqual(self.opened[0].closed,1)
 async def test_wrong_peer_closed(self):
  async def f(peer,cancel):return await self.factory('wrong',cancel)
  r=await self.check(f).run();self.assertIn('PEER_MISMATCH',r['reason']);self.assertEqual(self.opened[0].closed,1)
 async def test_cancelled_factory_must_not_allocate(self):
  async def f(peer,cancel):return await self.factory(peer,asyncio.Event())
  r=await self.check(f).run();self.assertIn('PRECANCEL_NOT_REJECTED',r['reason']);self.assertTrue(all(c.closed==1 for c in self.opened))
 async def test_probe_failure_is_not_pass(self):
  async def bad(c):return False
  r=await self.check(self.factory,bad).run();self.assertEqual(r['result'],'FAIL');self.assertTrue(r['cleanup_complete'])
 async def test_close_failure_is_retained(self):
  async def f(peer,cancel):
   c=await self.factory(peer,cancel)
   async def fail():raise OSError('close failed')
   c.close=fail;return c
  r=await self.check(f).run();self.assertEqual(r['result'],'FAIL');self.assertFalse(r['cleanup_complete']);self.assertGreater(r['retained'],0)
 async def test_timeout_retains_task_and_late_connection(self):
  entered=asyncio.Event();release=asyncio.Event()
  async def f(peer,cancel):entered.set();await release.wait();return await self.factory(peer,asyncio.Event())
  c=self.check(f);task=asyncio.create_task(c.run(timeout=.03));await entered.wait();r=await task
  self.assertEqual(r['result'],'FAIL');self.assertFalse(r['cleanup_complete']);release.set();r=await c.finish(timeout=1)
  self.assertEqual(r['result'],'FAIL');self.assertTrue(r['cleanup_complete']);self.assertEqual(self.opened[0].closed,1)
 async def test_probe_run_is_one_shot(self):
  c=self.check(self.factory);await c.run()
  with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):await c.run()
