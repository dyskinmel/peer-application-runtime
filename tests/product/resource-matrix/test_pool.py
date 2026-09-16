import asyncio, importlib, importlib.util, unittest

class Connection:
    def __init__(self, peer):
        self.peer=peer; self.closed=0; self.close_entered=asyncio.Event(); self.release=None; self.fail=False
    async def close(self):
        self.closed+=1; self.close_entered.set()
        if self.release: await self.release.wait()
        if self.fail: raise OSError('injected close failure')

class PoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(importlib.util.find_spec('product.wp13.par_matrix.pool'), 'bounded fair pool missing')
        self.m=importlib.import_module('product.wp13.par_matrix.pool'); self.pools=[]; self.connections=[]
    def pool(self, **kw):
        p=self.m.FairConnectionPool(('a','b','c'),**kw); self.pools.append(p);return p
    async def factory(self,peer,cancel):
        c=Connection(peer);self.connections.append(c);return c
    async def operation(self,c,cancel):return c.peer
    async def asyncTearDown(self):
        for c in getattr(self,'connections',[]):
            if c.release:c.release.set()
        for p in getattr(self,'pools',[]):await p.close(timeout=1)
    async def test_normal_closes_before_success(self):
        p=self.pool();h=p.submit('a','1',self.factory,self.operation);r=await h.wait()
        self.assertEqual(r.code,'OK');self.assertEqual(r.value,'a');self.assertEqual(self.connections[0].closed,1);self.assertEqual(p.status()['active'],0)
    async def test_invalid_limits(self):
        for kw in ({'max_active':0},{'max_active':9},{'max_queued':0},{'per_peer':9},{'max_active':True}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.pool(**kw)
    async def test_unknown_peer_rejected(self):
        p=self.pool()
        with self.assertRaisesRegex(ValueError,'PEER'):p.submit('alien','1',self.factory,self.operation)
    async def test_missing_factory_rejected_without_fallback(self):
        p=self.pool()
        with self.assertRaisesRegex(ValueError,'FACTORY'):p.submit('a','1',None,self.operation)
        self.assertEqual(p.status()['submitted'],0)
    async def test_duplicate_id_after_completion_rejected(self):
        p=self.pool();await p.submit('a','1',self.factory,self.operation).wait()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ID'):p.submit('b','1',self.factory,self.operation)
    async def test_queue_overflow_no_factory_call(self):
        p=self.pool(max_active=1,max_queued=1);entered=asyncio.Event()
        async def blocked(c,cancel):entered.set();await cancel.wait()
        h=p.submit('a','1',self.factory,blocked);await entered.wait();h2=p.submit('b','2',self.factory,self.operation)
        with self.assertRaisesRegex(ValueError,'QUEUE_FULL'):p.submit('c','3',self.factory,self.operation)
        self.assertEqual(len(self.connections),1);h.cancel();await h.wait();await h2.wait()
    async def test_peer_queue_bound(self):
        p=self.pool(max_active=1,per_peer=1);gate=asyncio.Event()
        async def block(c,cancel):gate.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await gate.wait();p.submit('a','2',self.factory,self.operation)
        with self.assertRaisesRegex(ValueError,'PEER_QUEUE_FULL'):p.submit('a','3',self.factory,self.operation)
        h.cancel()
    async def test_round_robin_not_global_fifo(self):
        p=self.pool(max_active=1);gate=asyncio.Event();release=asyncio.Event();order=[]
        async def block(c,cancel):gate.set();await release.wait()
        h=p.submit('a','a0',self.factory,block);await gate.wait()
        async def op(c,cancel):order.append(c.peer)
        hs=[p.submit(peer,rid,self.factory,op)for peer,rid in [('a','a1'),('a','a2'),('b','b1'),('c','c1')]]
        release.set();await h.wait();await asyncio.gather(*(x.wait() for x in hs));self.assertEqual(order,['b','c','a','a'])
    async def test_slow_peer_does_not_block_other_with_spare_slot(self):
        p=self.pool(max_active=2);entered=asyncio.Event()
        async def block(c,cancel):entered.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await entered.wait();r=await p.submit('b','2',self.factory,self.operation).wait()
        self.assertEqual(r.code,'OK');self.assertEqual(p.status()['active'],1);h.cancel()
    async def test_queued_cancel_skips_factory(self):
        p=self.pool(max_active=1);gate=asyncio.Event()
        async def block(c,cancel):gate.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await gate.wait();q=p.submit('b','2',self.factory,self.operation);q.cancel()
        self.assertEqual((await q.wait()).code,'CANCELLED_BEFORE_START');self.assertEqual(len(self.connections),1);h.cancel()
    async def test_active_cancel_keeps_slot_until_cleanup(self):
        p=self.pool(max_active=1);entered=asyncio.Event();release=asyncio.Event()
        async def block(c,cancel):entered.set();await release.wait()
        h=p.submit('a','1',self.factory,block);await entered.wait();self.assertTrue(h.cancel());self.assertFalse(h.cancel())
        self.assertEqual((await h.wait()).code,'CANCELLED_AFTER_START');self.assertEqual(p.status()['active'],1)
        release.set();self.assertTrue(await p.close(timeout=1))
    async def test_late_factory_result_closed_without_operation(self):
        p=self.pool();entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def factory(peer,cancel):entered.set();await release.wait();return await self.factory(peer,cancel)
        async def op(c,cancel):calls.append('bad')
        h=p.submit('a','1',factory,op);await entered.wait();h.cancel();await h.wait();release.set();await p.close(timeout=1)
        self.assertEqual(calls,[]);self.assertEqual(self.connections[0].closed,1)
    async def test_close_failure_retains_resource_and_stops_admission(self):
        p=self.pool()
        async def factory(peer,cancel):c=await self.factory(peer,cancel);c.fail=True;return c
        r=await p.submit('a','1',factory,self.operation).wait();self.assertEqual(r.code,'CLEANUP_FAILED')
        self.assertEqual(p.status()['retained'],1);self.assertFalse(await p.close(timeout=.01))
        with self.assertRaisesRegex(ValueError,'CLOSED|FAILED'):p.submit('b','2',self.factory,self.operation)
    async def test_slow_close_counts_as_active(self):
        p=self.pool(max_active=1);release=asyncio.Event()
        async def factory(peer,cancel):c=await self.factory(peer,cancel);c.release=release;return c
        h=p.submit('a','1',factory,self.operation)
        while not self.connections:await asyncio.sleep(0)
        await self.connections[0].close_entered.wait();self.assertEqual(p.status()['active'],1)
        self.assertFalse(await p.close(timeout=.01));release.set();self.assertTrue(await p.close(timeout=1));self.assertEqual(self.connections[0].closed,1)
    async def test_caller_task_cancel_does_not_cancel_worker(self):
        p=self.pool();entered=asyncio.Event();release=asyncio.Event()
        async def op(c,cancel):entered.set();await release.wait()
        h=p.submit('a','1',self.factory,op);t=asyncio.create_task(h.wait());await entered.wait();t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
        self.assertEqual(p.status()['active'],1);release.set();await p.close(timeout=1);self.assertEqual(self.connections[0].closed,1)
    async def test_expire_queued_before_factory(self):
        p=self.pool(max_active=1);entered=asyncio.Event()
        async def block(c,cancel):entered.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await entered.wait();q=p.submit('b','2',self.factory,self.operation)
        p._expire('2');self.assertEqual((await q.wait()).code,'TIMEOUT_BEFORE_START');self.assertEqual(len(self.connections),1);h.cancel()
    async def test_expire_active_releases_cooperatively(self):
        p=self.pool();entered=asyncio.Event()
        async def block(c,cancel):entered.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await entered.wait();p._expire('1')
        self.assertEqual((await h.wait()).code,'TIMEOUT_AFTER_START');await p.close(timeout=1);self.assertEqual(self.connections[0].closed,1)
    async def test_factory_failure_not_retried(self):
        p=self.pool();calls=[]
        async def fail(peer,cancel):calls.append(peer);raise OSError('offline')
        r=await p.submit('a','1',fail,self.operation).wait();self.assertEqual(r.code,'FACTORY_FAILED');self.assertEqual(calls,['a'])
    async def test_operation_failure_closes_once(self):
        p=self.pool()
        async def fail(c,cancel):raise OSError('read failed')
        r=await p.submit('a','1',self.factory,fail).wait();self.assertEqual(r.code,'OPERATION_FAILED');self.assertEqual(self.connections[0].closed,1)
    async def test_foreign_context_closed_no_operation(self):
        p=self.pool();calls=[]
        async def factory(peer,cancel):return await self.factory('wrong',cancel)
        async def op(c,cancel):calls.append(1)
        r=await p.submit('a','1',factory,op).wait();self.assertEqual(r.code,'PEER_MISMATCH');self.assertEqual(calls,[]);self.assertEqual(self.connections[0].closed,1)
    async def test_duplicate_connection_never_closed_by_second_owner(self):
        p=self.pool(max_active=2);entered=asyncio.Event();release=asyncio.Event();c=Connection('a');self.connections.append(c)
        async def factory(peer,cancel):return c
        async def block(c,cancel):entered.set();await release.wait()
        h=p.submit('a','1',factory,block);await entered.wait();r=await p.submit('b','2',factory,self.operation).wait()
        self.assertEqual(r.code,'DUPLICATE_CONNECTION');self.assertEqual(c.closed,0);release.set();await p.close(timeout=1);self.assertEqual(c.closed,1)
    async def test_status_copy_cannot_mutate_queue(self):
        p=self.pool();s=p.status();s['active']=999;self.assertEqual(p.status()['active'],0)
    async def test_close_discards_queued_without_starting(self):
        p=self.pool(max_active=1);entered=asyncio.Event()
        async def block(c,cancel):entered.set();await cancel.wait()
        h=p.submit('a','1',self.factory,block);await entered.wait();q=p.submit('b','2',self.factory,self.operation)
        self.assertTrue(await p.close(timeout=1));self.assertEqual((await q.wait()).code,'CANCELLED_BEFORE_START');self.assertEqual(len(self.connections),1)
    async def test_invalid_id_and_timeout_before_admission(self):
        p=self.pool()
        for rid,timeout in [('',1),('x'*65,1),('ok',float('nan')),('ok',0),('ok',True)]:
            with self.subTest(rid=rid,timeout=timeout),self.assertRaises(ValueError):p.submit('a',rid,self.factory,self.operation,timeout=timeout)
        self.assertEqual(p.status()['submitted'],0)
