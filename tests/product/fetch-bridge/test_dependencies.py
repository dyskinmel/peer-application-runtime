import asyncio, importlib, importlib.util, unittest
from fetch_support import AsyncFixture
from process_fixture import h
from par_crypto import objects
from product.wp09.par_secure_fetch import FetchError

class DependencyTests(AsyncFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_secure_fetch.dependencies'),'dependency planner missing')
        self.mod=importlib.import_module('product.wp09.par_secure_fetch.dependencies')
        self.a,self.b=self.remote.chain();self.target=objects.envelope_id(self.b[0]);self.local.box.receive(*self.b)
    def planner(self):return self.mod.DependencyPlanner(self.local.source,self.binding,lambda:self.gen[0])
    async def open(self):return await self.session()
    async def test_missing_inner_proposal_no_receive(self):
        before=self.local.box.pin();p=await self.planner().build([self.target],self.open)
        self.assertEqual(p.state,'FETCH_PROPOSED');self.assertEqual(p.plan.descriptors[0][0],h('inner:a'))
        self.assertEqual(p.targets,(self.target,));self.assertEqual(self.local.box.pin(),before)
        self.assertIs(p.accept(self.local.source,lambda:9),p.plan)
    async def test_ready_targets_need_no_network(self):
        self.local.box.receive(*self.a)
        async def forbid():self.fail('unexpected network')
        p=await self.planner().build([self.target],forbid)
        self.assertIsNone(p.plan);self.assertEqual(p.state,'NO_FETCH_REQUIRED')
    async def test_target_input_owned_before_await(self):
        roots=[self.target]
        async def altered():roots[0]=h('other');return await self.session()
        p=await self.planner().build(roots,altered);self.assertEqual(p.targets,(self.target,))
    async def test_no_unknown_target(self):
        with self.assertRaisesRegex(FetchError,'TARGET_NOT_OBSERVED'):await self.planner().build([h('missing')],self.open)
    async def test_duplicate_targets_rejected(self):
        with self.assertRaises(FetchError):await self.planner().build([self.target]*2,self.open)
    async def test_empty_targets_rejected(self):
        with self.assertRaises(FetchError):await self.planner().build([],self.open)
    async def test_invalid_identifier_rejected(self):
        with self.assertRaises(FetchError):await self.planner().build([bytearray(32)],self.open)
    async def test_bool_budget_rejected(self):
        with self.assertRaises(FetchError):await self.planner().build([self.target],self.open,max_records=True)
    async def test_missing_offer_does_not_become_empty_plan(self):
        self.remote.box.close()
        # A distinct valid Store/Inbox view has no advertised ancestor.
        from product.wp04.inbox import SyncInbox
        from product.wp04.exchange import Source
        self.remote.box=SyncInbox.create(self.root/'empty',self.remote.db,**self.remote.scope)
        d=self.remote.s.devices[0];self.remote.source=Source(self.remote.box,d['cert'],d['seed'])
        with self.assertRaisesRegex(FetchError,'DEPENDENCY_NOT_OFFERED'):await self.planner().build([self.target],self.open)
    async def test_byte_budget_rejected(self):
        with self.assertRaisesRegex(FetchError,'PLAN_BYTE_BUDGET'):await self.planner().build([self.target],self.open,max_bytes=1)
    async def test_query_budget_finite(self):
        with self.assertRaisesRegex(FetchError,'QUERY_BUDGET'):await self.planner().build([self.target],self.open,max_queries=1)
    async def test_local_change_mid_query_rejected(self):
        async def changed():s=await self.session();self.local.box.receive(*self.a);return s
        with self.assertRaisesRegex(FetchError,'LOCAL_VIEW_CHANGED'):await self.planner().build([self.target],changed)
    async def test_accept_rechecks_local_view(self):
        p=await self.planner().build([self.target],self.open);self.local.box.receive(*self.a)
        with self.assertRaisesRegex(FetchError,'LOCAL_VIEW_CHANGED'):p.accept(self.local.source,lambda:9)
    async def test_accept_rechecks_generation(self):
        p=await self.planner().build([self.target],self.open)
        with self.assertRaisesRegex(FetchError,'STALE_GENERATION'):p.accept(self.local.source,lambda:10)
    async def test_generation_change_during_open(self):
        async def changed():s=await self.session();self.gen[0]+=1;return s
        with self.assertRaisesRegex(FetchError,'STALE_GENERATION'):await self.planner().build([self.target],changed)
    async def test_cancel_before_open(self):
        c=asyncio.Event();c.set()
        async def forbid():self.fail('unexpected open')
        with self.assertRaisesRegex(FetchError,'CANCELLED'):await self.planner().build([self.target],forbid,cancel=c)
    async def test_cancel_during_factory_and_no_child_left(self):
        entered=asyncio.Event();cleaned=asyncio.Event();c=asyncio.Event()
        async def waiting():
            entered.set()
            try:await asyncio.Event().wait()
            finally:cleaned.set()
        t=asyncio.create_task(self.planner().build([self.target],waiting,cancel=c));await entered.wait();c.set()
        with self.assertRaisesRegex(FetchError,'CANCELLED'):await t
        self.assertTrue(cleaned.is_set())
    async def test_timeout_during_factory(self):
        # Real asyncio timeout, fired only after the factory owns a resource.
        # Synchronous authorization must not race an arbitrary 50ms wall budget.
        from unittest.mock import patch
        cleaned=asyncio.Event();entered=asyncio.Event();contexts=[]
        original=asyncio.timeout_at
        def capture(deadline):
            context=original(deadline);contexts.append(context);return context
        async def waiting():
            entered.set();contexts[-1].reschedule(asyncio.get_running_loop().time())
            try:await asyncio.Event().wait()
            finally:cleaned.set()
        with patch('asyncio.timeout_at',capture):
            with self.assertRaisesRegex(FetchError,'PLAN_TIMEOUT'):
                await self.planner().build([self.target],waiting,timeout=30)
        self.assertTrue(entered.is_set());self.assertTrue(cleaned.is_set())
    async def test_expiry_before_factory_does_not_allocate(self):
        from unittest.mock import patch
        clock=[0.0];inspect=self.local.box.inspect;entered=[]
        def slow(eid):
            result=inspect(eid);clock[0]=1.0;return result
        async def forbidden():entered.append(True);self.fail('factory started after expiry')
        with patch.object(self.local.box,'inspect',slow),patch.object(asyncio.get_running_loop(),'time',lambda:clock[0]):
            with self.assertRaisesRegex(FetchError,'PLAN_TIMEOUT'):
                await self.planner().build([self.target],forbidden,timeout=.05)
        self.assertEqual(entered,[])
    async def test_task_cancel_propagates(self):
        entered=asyncio.Event()
        async def waiting():entered.set();await asyncio.Event().wait()
        t=asyncio.create_task(self.planner().build([self.target],waiting));await entered.wait();t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
    async def test_previous_only_uses_full_paged_catalog(self):
        # The predecessor may be unknown without an inner-ID offer. This is only
        # planning; its noncausal relationship is rejected by later validation.
        prev=self.remote.change('previous-only',3,[],objects.envelope_id(self.a[0]));self.local.box.receive(*prev)
        p=await self.planner().build([objects.envelope_id(prev[0])],self.open,page_size=1)
        self.assertEqual(p.plan.descriptors[0][1],objects.envelope_id(self.a[0]))
    async def test_remote_change_between_pages_stops(self):
        prev=self.remote.change('previous-only',3,[],objects.envelope_id(self.a[0]));self.local.box.receive(*prev);n=0
        async def changed():
            nonlocal n
            n+=1
            if n==2:self.remote.box.receive(*self.remote.change('c',3,[h('inner:b')],self.target))
            return await self.session()
        with self.assertRaises(FetchError):await self.planner().build([objects.envelope_id(prev[0])],changed,page_size=1)
    async def test_proposal_is_immutable(self):
        p=await self.planner().build([self.target],self.open)
        with self.assertRaises((AttributeError,TypeError)):p.targets=()
        self.assertEqual(len(p.digest),64)
    async def test_busy_is_rejected(self):
        obj=self.planner();entered=asyncio.Event();c=asyncio.Event()
        async def wait():entered.set();await asyncio.Event().wait()
        t=asyncio.create_task(obj.build([self.target],wait,cancel=c));await entered.wait()
        with self.assertRaisesRegex(FetchError,'PLANNER_BUSY'):await obj.build([self.target],self.open)
        c.set()
        with self.assertRaises(FetchError):await t
    async def test_three_levels_are_explicit_frontier_rounds(self):
        c=self.remote.change('c',3,[h('inner:b')],self.target);self.remote.box.receive(*c)
        # Start from c only on a fresh Inbox.
        from product.wp04.inbox import SyncInbox
        from product.wp04.exchange import Source
        self.local.box.close();self.local.box=SyncInbox.create(self.root/'receiver-c',self.local.db,**self.local.scope)
        d=self.local.s.devices[1];self.local.source=Source(self.local.box,d['cert'],d['seed']);self.local.box.receive(*c)
        root=objects.envelope_id(c[0]);p=await self.planner().build([root],self.open)
        self.assertEqual([d[0]for d in p.plan.descriptors],[h('inner:b')])
        self.local.box.receive(*self.b);p2=await self.planner().build([root],self.open)
        self.assertEqual([d[0]for d in p2.plan.descriptors],[h('inner:a')])
        self.local.box.receive(*self.a);p3=await self.planner().build([root],self.open);self.assertIsNone(p3.plan)
    async def test_cancel_during_synchronous_inspection_rejected_on_ready_path(self):
        self.local.box.receive(*self.a);cancel=asyncio.Event();inspect=self.local.box.inspect
        def cancelling(eid):
            result=inspect(eid);cancel.set();return result
        self.local.box.inspect=cancelling
        async def forbidden():self.fail('no network expected')
        with self.assertRaisesRegex(FetchError,'CANCELLED'):
            await self.planner().build([self.target],forbidden,cancel=cancel)
    async def test_deadline_after_synchronous_inspection_rejected_on_ready_path(self):
        from unittest.mock import patch
        self.local.box.receive(*self.a);inspect=self.local.box.inspect;clock=[0.0]
        def slow(eid):
            result=inspect(eid);clock[0]=1.0;return result
        self.local.box.inspect=slow
        async def forbidden():self.fail('no network expected')
        with patch.object(asyncio.get_running_loop(),'time',lambda:clock[0]):
            with self.assertRaisesRegex(FetchError,'PLAN_TIMEOUT'):
                await self.planner().build([self.target],forbidden,timeout=.05)
    async def test_existing_cycle_stops_without_remote_queries(self):
        # Sign/encrypt real envelopes with a synthetic inner graph a <-> b.
        from product.wp04.inbox import SyncInbox
        from product.wp04.exchange import Source
        self.local.box.close();self.local.box=SyncInbox.create(self.root/'cycle',self.local.db,**self.local.scope)
        d=self.local.s.devices[1];self.local.source=Source(self.local.box,d['cert'],d['seed'])
        a=self.remote.change('cycle-a',1,[h('inner:cycle-b')]);b=self.remote.change('cycle-b',2,[h('inner:cycle-a')],objects.envelope_id(a[0]))
        self.local.box.receive(*a);self.local.box.receive(*b)
        async def forbidden():self.fail('invalid local graph must not issue network calls')
        with self.assertRaisesRegex(FetchError,'INVALID_DEPENDENCY_GRAPH'):
            await self.planner().build([objects.envelope_id(a[0])],forbidden)
