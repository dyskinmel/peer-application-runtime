import asyncio,unittest
from unittest.mock import patch
from fetch_support import AsyncFixture,h,tls

class ClientTests(AsyncFixture,unittest.IsolatedAsyncioTestCase):
    async def test_explicit_get_persists_candidate_only(self):
        c=self.client();v=await c.fetch_one(0,await self.session());self.assertEqual(v['stored'],1)
        self.assertFalse(v['applied']or v['acknowledged']or v['localCommitted']);self.assertEqual(self.local.box.usage()['records'],1)
        self.assertTrue(all(s.closed for s in self.streams));self.assertEqual(self.local.db._storage.connection.execute('SELECT COUNT(*) FROM commit_ledger').fetchone()[0],0)
    async def test_explicit_batch_each_item_once(self):
        c=self.client();calls=[]
        async def opener(i):calls.append(i);return await self.session()
        v=await c.execute(opener);self.assertEqual(v['stored'],2);self.assertEqual(calls,[0,1])
        await c.execute(opener);self.assertEqual(calls,[0,1]);self.assertEqual(self.local.box.usage()['records'],2)
    async def test_batch_selection(self):
        c=self.client();v=await c.execute(lambda i:self.session(),indices=[1]);self.assertEqual(v['stored'],1)
    async def test_batch_rejects_duplicate_indices(self):
        with self.assertRaises(self.m.FetchError):await self.client().execute(lambda i:self.session(),indices=[0,0])
    async def test_rejects_bool_index(self):
        s=await self.session()
        with self.assertRaises(self.m.FetchError):await self.client().fetch_one(True,s)
        self.assertTrue(s.stream.closed)
    async def test_pre_cancel_no_receive(self):
        c=self.client();s=await self.session();e=asyncio.Event();e.set()
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s,cancel=e)
        self.assertEqual(self.local.box.usage()['records'],0);self.assertTrue(s.stream.closed)
    async def test_cancel_after_read_before_receive(self):
        c=self.client();s=await self.session();e=asyncio.Event();original=s.request
        async def cancelled(*a,**kw):v=await original(*a,**kw);e.set();return v
        with patch.object(s,'request',cancelled):
            with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s,cancel=e)
        self.assertEqual(self.local.box.usage()['records'],0)
    async def test_task_cancel_during_request(self):
        c=self.client();s=await self.session();entered=asyncio.Event()
        async def stall(*a,**kw):entered.set();await asyncio.Event().wait()
        with patch.object(s,'request',stall):
            t=asyncio.create_task(c.fetch_one(0,s));await entered.wait();t.cancel()
            with self.assertRaises(asyncio.CancelledError):await t
        self.assertEqual(self.local.box.usage()['records'],0);self.assertTrue(s.stream.closed)
    async def test_cancel_after_store_preserves_record(self):
        c=self.client();s=await self.session();e=asyncio.Event()
        self.local.box.observer=lambda name:e.set()if name=='inbox.before_receipt'else None
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s,cancel=e)
        self.assertEqual(self.local.box.usage()['records'],1);self.assertEqual(c.progress()['stored'],1)
    async def test_generation_after_read_no_store(self):
        c=self.client();s=await self.session();original=s.request
        async def stale(*a,**kw):v=await original(*a,**kw);self.gen[0]=10;return v
        with patch.object(s,'request',stale):
            with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s)
        self.assertEqual(self.local.box.usage()['records'],0)
    async def test_generation_after_store_not_claimed_complete(self):
        c=self.client();self.local.box.observer=lambda name:self.gen.__setitem__(0,10)if name=='inbox.before_receipt'else None
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,await self.session())
        self.assertEqual(c.progress()['stored'],1);self.assertNotEqual(c.progress()['state'],'COMPLETE_PENDING')
    async def test_wrong_binding_rejected(self):
        c=self.client();s=await self.session();s.binding=tls.PeerBinding('another',self.binding.certificate,self.binding.scope,self.binding.peer_sha256,9)
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s)
        self.assertTrue(s.stream.closed);self.assertEqual(self.local.box.usage()['records'],0)
    async def test_snapshot_change_requires_new_plan(self):
        c=self.client();self.remote.box.receive(*self.remote.change('new',seq=3,parents=[h('inner:b')],previous=self.descriptors[next(i for i,d in enumerate(self.descriptors)if d[0]==h('inner:b'))][1]))
        with self.assertRaises(Exception):await c.fetch_one(0,await self.session())
        self.assertEqual(self.local.box.usage()['records'],0);self.assertNotEqual(c.progress()['state'],'COMPLETE_PENDING')
    async def test_bad_length_rejected_before_store(self):
        ds=[list(d)for d in self.descriptors];ds[0][2]+=1;c=self.client(self.make_plan(descriptors=ds))
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,await self.session())
        self.assertEqual(self.local.box.usage()['records'],0)
    async def test_signed_descriptor_is_not_envelope_permission(self):
        c=self.client();s=await self.session();d=c.plan.descriptors[0];raw,cert=self.remote.chain()[0]
        async def bad(*a,**kw):return {0:c.plan.snapshot,1:d[0],2:d[1],3:raw[:-1]+bytes([raw[-1]^1]),4:cert,5:'ENCRYPTED_PENDING_BYTES'}
        with patch.object(s,'request',bad):
            with self.assertRaises(Exception):await c.fetch_one(0,s)
        self.assertEqual(self.local.box.usage()['records'],0)
    async def test_batch_stops_no_auto_retry_after_failure(self):
        c=self.client();calls=[]
        async def opener(i):calls.append(i);raise OSError('fixture unavailable')
        with self.assertRaises(self.m.FetchError):await c.execute(opener)
        self.assertEqual(calls,[0]);self.assertEqual(c.progress()['stored'],0)
    async def test_partial_batch_keeps_first_record(self):
        c=self.client();calls=[]
        async def opener(i):
            calls.append(i)
            if i==1:raise OSError('fixture unavailable')
            return await self.session()
        with self.assertRaises(self.m.FetchError):await c.execute(opener)
        self.assertEqual(calls,[0,1]);self.assertEqual(c.progress()['stored'],1)
        v=await c.execute(lambda i:self.session());self.assertEqual(v['stored'],2)
    async def test_concurrent_call_is_busy(self):
        c=self.client();s=await self.session();entered=asyncio.Event();release=asyncio.Event();original=s.request
        async def paused(*a,**kw):entered.set();await release.wait();return await original(*a,**kw)
        with patch.object(s,'request',paused):
            t=asyncio.create_task(c.fetch_one(0,s));await entered.wait()
            with self.assertRaises(self.m.FetchError):c.reconcile()
            release.set();await t
    async def test_receipt_loss_requires_reopen_then_reconcile(self):
        c=self.client()
        def fail(name):
            if name=='inbox.before_receipt':raise RuntimeError('lost response')
        self.local.box.observer=fail
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,await self.session())
        self.assertEqual(c.progress()['items'][0]['state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(self.m.FetchError):c.reconcile()
    async def test_missing_dependency_not_applied(self):
        ds=sorted(self.descriptors,key=lambda d: d[0]!=h('inner:b'));c=self.client(self.make_plan(descriptors=ds));v=await c.fetch_one(0,await self.session())
        self.assertEqual(v['items'][0]['candidateState'],'WAITING_DEPENDENCIES');self.assertFalse(v['applied'])
    async def test_ui_projection_does_not_expose_content(self):
        c=self.client();await c.fetch_one(0,await self.session());v=self.m.present_progress(c.progress(),locale='ja')
        self.assertEqual(v['kind'],'encrypted-candidate-progress');self.assertFalse(v['applied']);self.assertIn('未適用',v['message']);self.assertNotIn('envelopeId',str(v))
    async def test_ui_unknown_not_saved(self):
        c=self.client();v=c.progress();v['state']='RECONCILE_REQUIRED';v['items'][0]['state']='OUTCOME_UNKNOWN'
        ui=self.m.present_progress(v,locale='en');self.assertIn('unknown',ui['message']);self.assertFalse(ui['applied'])
    async def test_cached_record_is_revalidated_not_blindly_skipped(self):
        c=self.client();await c.fetch_one(0,await self.session());path=self.local.box.root/'records'/(c.plan.descriptors[0][1].hex()+'.cbor');path.unlink()
        with self.assertRaises(self.m.FetchError):await c.fetch_one(0,await self.session())
    async def test_final_cleanup_generation_change_stops_progress(self):
        c=self.client(self.make_plan(descriptors=[self.descriptors[0]]));s=await self.session();original=s.stream.close;calls=[0]
        async def close():
            await original();calls[0]+=1
            if calls[0]>=2:self.gen[0]=10
        with patch.object(s.stream,'close',close):
            with self.assertRaises(self.m.FetchError):await c.fetch_one(0,s)
        self.assertEqual(c.progress()['state'],'STOPPED');self.assertEqual(c.progress()['stored'],1)
    async def test_cancel_during_factory_reaps_late_session(self):
        c=self.client();s=await self.session();entered=asyncio.Event();cancel=asyncio.Event();seen=[]
        async def opener(i):
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:seen.append('cancelled');return s
        t=asyncio.create_task(c.execute(opener,cancel=cancel,timeout=.5));await entered.wait();cancel.set()
        with self.assertRaises(self.m.FetchError):await asyncio.wait_for(t,1)
        self.assertEqual(seen,['cancelled']);self.assertTrue(s.stream.closed);self.assertEqual(self.local.box.usage()['records'],0)
    async def test_factory_event_cancel_stops_promptly(self):
        c=self.client();entered=asyncio.Event();cancel=asyncio.Event();left=asyncio.Event()
        async def opener(i):
            entered.set()
            try:await asyncio.Event().wait()
            finally:left.set()
        t=asyncio.create_task(c.execute(opener,cancel=cancel,timeout=1));await entered.wait();cancel.set()
        with self.assertRaises(self.m.FetchError):await asyncio.wait_for(t,.3)
        self.assertTrue(left.is_set())
    async def test_synchronous_save_overrun_not_deadline_success(self):
        # Advance a controlled monotonic clock only AFTER receive. Host load
        # must not turn this into a pre-save network timeout test.
        c=self.client(self.make_plan(descriptors=[self.descriptors[0]]));original=self.local.box.receive
        loop=asyncio.get_running_loop();clock=loop.time;offset=[0.0]
        def slow(*a):
            receipt=original(*a);offset[0]=31.0;return receipt
        with patch.object(self.local.box,'receive',slow),patch.object(loop,'time',lambda:clock()+offset[0]):
            with self.assertRaises(self.m.FetchError):await c.execute(lambda i:self.session(),timeout=30)
        self.assertEqual(self.local.box.usage()['records'],1);self.assertEqual(c.progress()['state'],'STOPPED')
    async def test_cancelled_task_after_save_not_complete_state(self):
        c=self.client(self.make_plan(descriptors=[self.descriptors[0]]))
        self.local.box.observer=lambda name:asyncio.current_task().cancel()if name=='inbox.before_receipt'else None
        task=asyncio.create_task(c.fetch_one(0,await self.session()))
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(c.progress()['stored'],1);self.assertEqual(c.progress()['state'],'STOPPED')
    async def test_final_cleanup_failure_does_not_leave_complete_state(self):
        c=self.client(self.make_plan(descriptors=[self.descriptors[0]]));s=await self.session();original=s.stream.close;calls=[0]
        async def close():
            await original();calls[0]+=1
            if calls[0]>=2:raise OSError('fixture close failure')
        with patch.object(s.stream,'close',close):
            with self.assertRaises(Exception):await c.fetch_one(0,s)
        self.assertEqual(c.progress()['stored'],1);self.assertEqual(c.progress()['state'],'STOPPED')
    async def test_final_cleanup_cancellation_does_not_leave_complete_state(self):
        c=self.client(self.make_plan(descriptors=[self.descriptors[0]]));s=await self.session();original=s.stream.close;calls=[0]
        async def close():
            await original();calls[0]+=1
            if calls[0]>=2:raise asyncio.CancelledError
        with patch.object(s.stream,'close',close):
            with self.assertRaises(asyncio.CancelledError):await c.fetch_one(0,s)
        self.assertEqual(c.progress()['stored'],1);self.assertEqual(c.progress()['state'],'STOPPED')
