"""The baseline may exhaust its deadline before allocating a factory resource."""
import asyncio,time,unittest
from unittest.mock import patch
import test_owner_hardening as support
from fetch_support import AsyncFixture
from product.wp10.events import EventError
class OwnerDeadlineRegression(AsyncFixture,unittest.IsolatedAsyncioTestCase):
    asyncSetUp=support.HardeningTests.asyncSetUp;asyncTearDown=support.HardeningTests.asyncTearDown
    make=support.HardeningTests.make;call=support.HardeningTests.call;observed=support.HardeningTests.observed
    async def test_expiry_before_factory_does_not_allocate(self):
        entered=asyncio.Event();finished=asyncio.Event()
        async def factory():
            entered.set()
            try:await asyncio.Event().wait()
            finally:finished.set()
        self.host._open=factory;v=await self.observed();original=self.host._planner._guard
        def deliberately_slow(*a,**kw):
            result=original(*a,**kw);time.sleep(.06);return result
        with patch.object(self.host._planner,'_guard',deliberately_slow):
            with self.assertRaisesRegex(EventError,'OWNER_DEADLINE|PLAN_TIMEOUT'):
                await self.call('propose',expectedRevision=v['observation']['revision'],timeoutMs=50)
        self.assertFalse(entered.is_set());self.assertFalse(finished.is_set());self.assertEqual(self.host.stats()['inflight'],0)
