import asyncio,copy,importlib,unittest
import test_owner as base
from fetch_support import AsyncFixture
from par_crypto import objects
from product.wp10.events import EventError

# Share fixture/setup/helpers, but do not duplicate the original test identities.
class HardeningTests(AsyncFixture,unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.OwnerTests.asyncSetUp;asyncTearDown=base.OwnerTests.asyncTearDown
    make=base.OwnerTests.make;call=base.OwnerTests.call;observed=base.OwnerTests.observed;proposed=base.OwnerTests.proposed;accepted=base.OwnerTests.accepted
    async def test_repeated_cancel_does_not_interrupt_cleanup(self):
        entered=asyncio.Event();cleaning=asyncio.Event();finish=asyncio.Event();cancel_count=0
        async def factory():
            nonlocal cancel_count
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_count+=1;cleaning.set();await finish.wait();raise
        self.host._open=factory
        v=await self.observed();f=self.host.request(self.ch,'propose',{'context':self.ctx,'expectedRevision':v['observation']['revision']})
        await entered.wait();f.cancel();await cleaning.wait();f.cancel();self.host.detach(self.ch);await asyncio.sleep(0)
        self.assertEqual(cancel_count,1);self.assertEqual(self.host.stats()['inflight'],1)
        with self.assertRaisesRegex(EventError,'OWNER_CHANNEL_LIMIT'):self.host.attach(allow_fetch=True)
        finish.set();await asyncio.wait_for(asyncio.gather(*(row[0]for row in list(self.host._jobs.values()))),1)
        self.assertEqual(self.host.stats()['inflight'],0)
    async def test_propose_deadline_reaps_factory(self):
        # The old 50ms budget could expire in synchronous authorization before
        # factory entry. Trigger the *real* owner Timeout only once it has started.
        from unittest.mock import patch
        finished=asyncio.Event();entered=asyncio.Event();contexts=[]
        original=asyncio.timeout_at
        def capture(deadline):
            context=original(deadline);contexts.append(context);return context
        async def factory():
            entered.set();contexts[0].reschedule(asyncio.get_running_loop().time())
            try:await asyncio.Event().wait()
            finally:finished.set()
        self.host._open=factory;v=await self.observed()
        with patch('asyncio.timeout_at',capture):
            with self.assertRaisesRegex(EventError,'OWNER_DEADLINE|PLAN_TIMEOUT'):
                await self.call('propose',expectedRevision=v['observation']['revision'],timeoutMs=30000)
        self.assertTrue(entered.is_set());self.assertTrue(finished.is_set());self.assertEqual(self.host.stats()['inflight'],0)
    async def test_proposal_expiry(self):
        self.host._proposal_seconds=.05;v=await self.proposed();await asyncio.sleep(.06)
        with self.assertRaisesRegex(EventError,'PROPOSAL_UNAVAILABLE'):await self.call('accept',expectedRevision=v['observation']['revision'],proposalId=v['proposal']['id'])
    async def test_saved_then_cancel_does_not_claim_success(self):
        a=await self.accepted();fut=None;save=self.local.box.receive
        def after(*a,**k):
            result=save(*a,**k)
            if fut is not None:fut.cancel()
            return result
        self.local.box.receive=after
        fut=self.host.request(self.ch,'fetch',{'context':self.ctx,'expectedRevision':a['observation']['revision'],'planDigest':a['selection']['planDigest']})
        with self.assertRaises(asyncio.CancelledError):await fut
        await asyncio.gather(*(row[0]for row in list(self.host._jobs.values())))
        self.assertEqual(self.local.box.usage()['records'],2)
        r=await self.observed();self.assertTrue(r['resumeRequired'])
    async def test_plan_storage_budget_fails_before_new_files(self):
        v=await self.proposed()
        for n in range(128):(self.root/'plans'/('occupied-'+str(n))).write_bytes(b'x')
        before=set((self.root/'plans').iterdir())
        with self.assertRaisesRegex(EventError,'OWNER_PLAN_BUDGET'):await self.call('accept',expectedRevision=v['observation']['revision'],proposalId=v['proposal']['id'])
        self.assertEqual(before,set((self.root/'plans').iterdir()))
    async def test_resumed_plan_still_checks_current_permission(self):
        a=await self.accepted();self.gen[0]=10
        with self.assertRaisesRegex(EventError,'STALE_GENERATION'):await self.call('resume',expectedRevision=a['observation']['revision'],planDigest=a['selection']['planDigest'])
    async def test_close_timeout_keeps_cleanup_reference(self):
        entered=asyncio.Event();cleanup=asyncio.Event();finish=asyncio.Event()
        async def factory():
            entered.set()
            try:await asyncio.Event().wait()
            finally:cleanup.set();await finish.wait()
        self.host._open=factory;v=await self.observed();f=self.host.request(self.ch,'propose',{'context':self.ctx,'expectedRevision':v['observation']['revision']});await entered.wait()
        result=await self.host.close();self.assertFalse(result['cleanupComplete']);self.assertEqual(result['inflight'],1)
        finish.set();await asyncio.gather(*(row[0]for row in list(self.host._jobs.values())));self.assertTrue((await self.host.close())['cleanupComplete'])
    async def test_context_replay_across_restart_rejected(self):
        old=copy.deepcopy(self.ctx);await self.host.close();self.host=self.make();self.ch=self.host.attach(allow_fetch=True);self.ctx=self.host.context(self.ch)
        self.assertNotEqual(old['streamId'],self.ctx['streamId'])
        with self.assertRaisesRegex(EventError,'OWNER_CONTEXT'):await self.host.request(self.ch,'observe',{'context':old})
