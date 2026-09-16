import asyncio, unittest

class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from product.wp14.par_native_provider import model,handoff
        self.m=model;self.h=handoff;self.epoch='11'*16

    def bundle(self,**kw):
        d=self.m.experimental_posix_descriptor(epoch=self.epoch)
        return self.h.ProviderBundle(d,**kw)

    async def test_missing_bundle_is_blocked_without_fallback(self):
        r=self.h.NativeProviderHandoff(None)
        self.assertEqual(r.status()['result'],'BLOCKED')
        self.assertEqual(r.status()['reason'],'PROVIDER_NOT_SUPPLIED')

    async def test_wrong_epoch_rejected_before_provider_use(self):
        calls=[]
        b=self.bundle(pin_factory=lambda *a:calls.append(a))
        h=self.h.NativeProviderHandoff(b)
        with self.assertRaisesRegex(ValueError,'PROVIDER_EPOCH'):h.open('22'*16)
        self.assertEqual(calls,[])

    async def test_doctor_does_not_invoke_factories(self):
        calls=[]
        b=self.bundle(pin_factory=lambda *a:calls.append(('pin',a)),connection_factory=lambda *a:calls.append(('dial',a)))
        h=self.h.NativeProviderHandoff(b);s=h.open(self.epoch)
        r=s.doctor();self.assertEqual(r['result'],'PASS');self.assertEqual(calls,[])

    async def test_precancelled_connection_never_calls_factory(self):
        calls=[]
        async def factory(peer,cancel):calls.append(peer);raise AssertionError('called')
        h=self.h.NativeProviderHandoff(self.bundle(connection_factory=factory));s=h.open(self.epoch);ev=asyncio.Event();ev.set()
        with self.assertRaisesRegex(ValueError,'CANCELLED'):await s.connect('peer-a',ev)
        self.assertEqual(calls,[])

    async def test_epoch_change_after_dial_closes_connection(self):
        epoch=[self.epoch];closed=[]
        class C:
            peer='peer-a'
            async def close(self):closed.append(True)
        async def factory(peer,cancel):epoch[0]='22'*16;return C()
        b=self.bundle(connection_factory=factory,epoch_reader=lambda:epoch[0]);s=self.h.NativeProviderHandoff(b).open(self.epoch)
        with self.assertRaisesRegex(ValueError,'PROVIDER_EPOCH_CHANGED'):await s.connect('peer-a',asyncio.Event())
        self.assertEqual(closed,[True])

    async def test_cancel_after_dial_closes_connection(self):
        closed=[];ev=asyncio.Event()
        class C:
            peer='peer-a'
            async def close(self):closed.append(True)
        async def factory(peer,cancel):cancel.set();return C()
        s=self.h.NativeProviderHandoff(self.bundle(connection_factory=factory)).open(self.epoch)
        with self.assertRaisesRegex(ValueError,'CANCELLED'):await s.connect('peer-a',ev)
        self.assertEqual(closed,[True])

    async def test_wrong_peer_is_closed_and_rejected(self):
        closed=[]
        class C:
            peer='other'
            async def close(self):closed.append(True)
        async def factory(peer,cancel):return C()
        s=self.h.NativeProviderHandoff(self.bundle(connection_factory=factory)).open(self.epoch)
        with self.assertRaisesRegex(ValueError,'PEER_MISMATCH'):await s.connect('peer-a',asyncio.Event())
        self.assertEqual(closed,[True])

    async def test_close_failure_retains_resource(self):
        class C:
            peer='peer-a'
            async def close(self):raise OSError('busy')
        async def factory(peer,cancel):return C()
        s=self.h.NativeProviderHandoff(self.bundle(connection_factory=factory)).open(self.epoch)
        c=await s.connect('peer-a',asyncio.Event())
        self.assertIs(c,s.connections()[0])
        self.assertFalse(await s.close())
        self.assertEqual(s.status()['retained'],1)
        self.assertFalse(s.status()['cleanupComplete'])

    async def test_successful_close_releases_owned_connection_once(self):
        count=[]
        class C:
            peer='peer-a'
            async def close(self):count.append(1)
        async def factory(peer,cancel):return C()
        s=self.h.NativeProviderHandoff(self.bundle(connection_factory=factory)).open(self.epoch)
        await s.connect('peer-a',asyncio.Event());self.assertTrue(await s.close());self.assertTrue(await s.close())
        self.assertEqual(count,[1]);self.assertTrue(s.status()['cleanupComplete'])

    async def test_pin_store_requires_declared_and_supplied_capability(self):
        s=self.h.NativeProviderHandoff(self.bundle()).open(self.epoch)
        with self.assertRaisesRegex(self.h.ProviderBlocked,'PIN_STORE_NOT_SUPPLIED'):s.open_pin_store('binding')

    async def test_epoch_reader_mismatch_blocks_pin_open(self):
        calls=[]
        epoch=[self.epoch]
        b=self.bundle(pin_factory=lambda binding:calls.append(binding),epoch_reader=lambda:epoch[0])
        s=self.h.NativeProviderHandoff(b).open(self.epoch);epoch[0]='22'*16
        with self.assertRaisesRegex(ValueError,'PROVIDER_EPOCH_CHANGED'):s.open_pin_store('binding')
        self.assertEqual(calls,[])

    async def test_closed_session_rejects_new_connection(self):
        s=self.h.NativeProviderHandoff(self.bundle()).open(self.epoch);self.assertTrue(await s.close())
        with self.assertRaisesRegex(ValueError,'SESSION_CLOSED'):await s.connect('peer-a',asyncio.Event())

if __name__=='__main__':unittest.main()
