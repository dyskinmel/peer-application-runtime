"""Owner capability tests: real files/SQLite, positive core explicitly SYNTHETIC."""
import asyncio, copy, importlib, importlib.util, unittest
from unittest.mock import patch
import test_intent_coordinator as fixtures
from product.wp09.par_application_intent import LocalPinStore, IntentJournal, AnchoredApplication

class ApplicationOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        name='product.wp09.par_application_owner.owner'
        self.assertIsNotNone(importlib.util.find_spec(name), 'versioned anchored owner missing')
        self.m=importlib.import_module(name)
        f=self.f=fixtures.IntentCoordinatorTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.anchor=LocalPinStore.create(f.root.parent/'anchor',AnchoredApplication.binding(f.c),f.j.pin()); self.addCleanup(self.anchor.close)
        f.j.close(); f.j=IntentJournal.open_anchored(f.root.parent/'intents',AnchoredApplication.binding(f.c),self.anchor); f.addCleanup(f.j.close)
        f.d=AnchoredApplication(f.j,f.c)
        self.o=self.m.ApplicationOwner(f.d,local_experiment=True); self.addAsyncCleanup(self.o.close)
        self.ch=self.o.attach(allow_apply=True); self.s=None
        await self.observe()
    async def call(self,op,**args):
        obj={'context':self.o.context(self.ch),**args}
        if op not in ('observe','close'):obj.setdefault('expectedRevision',self.s['observation']['revision'])
        result=await self.o.request(self.ch,op,obj)
        if op!='close':self.s=result
        return result
    async def observe(self):return await self.call('observe')
    async def prepare(self,**kw):return await self.call('prepare',operationId=(b'o'*16).hex(),expectedApplyRevision=0,targetDigest=self.o.context(self.ch)['document']['targetDigest'],**kw)
    async def action(self,op,**kw):
        i=self.s['intent'];return await self.call(op,operationId=i['operationId'],expectedApplyRevision=i['expectedRevision'],intentDigest=i['digest'],**kw)
    async def test_separate_profile_and_no_fetch_effects(self):
        self.assertEqual(self.s['profile'],'par-owner-application-0052');self.assertNotIn('fetch',self.s['operations'])
        self.assertFalse(self.s['journal']['applied']);self.assertEqual(self.s['journal']['state'],'EMPTY')
    async def test_default_readonly(self):
        self.o.detach(self.ch);self.ch=self.o.attach();await self.observe()
        with self.assertRaisesRegex(Exception,'OWNER_OPERATION_DENIED'):await self.prepare()
        self.assertEqual(self.f.j.status()['sequence'],0)
    async def test_production_mutation_refused(self):
        other=self.m.ApplicationOwner(self.f.d)
        try:
            with self.assertRaisesRegex(Exception,'LOCAL_EXPERIMENT_REQUIRED'):other.attach(allow_apply=True)
        finally:await other.close()
    async def test_unanchored_capability_refused(self):
        with self.assertRaisesRegex(Exception,'ANCHORED_APPLICATION_REQUIRED'):self.m.ApplicationOwner(object(),local_experiment=True)
    async def test_prepare_before_nonce_and_pin_matches(self):
        r=await self.prepare();self.assertEqual(r['journal']['state'],'PREPARED');self.assertEqual(self.anchor.load(),self.f.j.pin());self.assertEqual(self.f.nums()['document_apply_nonces'],0)
    async def test_wrong_context_rejected(self):
        ctx=copy.deepcopy(self.o.context(self.ch));ctx['journalId']='0'*64
        with self.assertRaisesRegex(Exception,'OWNER_CONTEXT'):await self.o.request(self.ch,'observe',{'context':ctx})
    async def test_extra_field_rejected(self):
        with self.assertRaisesRegex(Exception,'OWNER_SCHEMA'):await self.call('observe',extra=1)
    async def test_bool_revision_rejected(self):
        with self.assertRaisesRegex(Exception,'OWNER_SCHEMA'):await self.call('prepare',operationId='a'*32,expectedApplyRevision=True,targetDigest=self.o.context(self.ch)['document']['targetDigest'])
    async def test_wrong_target_rejected(self):
        with self.assertRaisesRegex(Exception,'APPLICATION_TARGETS'):await self.call('prepare',operationId='a'*32,expectedApplyRevision=0,targetDigest='0'*64)
    async def test_stale_observation_rejected(self):
        with self.assertRaisesRegex(Exception,'STALE_OBSERVATION'):await self.prepare(expectedRevision='0'*64)
    async def test_one_channel(self):
        with self.assertRaisesRegex(Exception,'OWNER_CHANNEL_LIMIT'):self.o.attach(allow_apply=True)
    async def test_one_worker(self):
        a=self.o.request(self.ch,'observe',{'context':self.o.context(self.ch)})
        with self.assertRaisesRegex(Exception,'OWNER_BUSY'):self.o.request(self.ch,'observe',{'context':self.o.context(self.ch)})
        await a
    async def test_unavailable_core_preserves_prepared(self):
        self.f.app._core=None;await self.prepare();r=await self.action('dispatch')
        self.assertEqual(r['journal']['operationState'],'CORE_BLOCKED');self.assertEqual(r['journal']['state'],'PREPARED');self.assertEqual(self.f.port.calls,0)
    async def test_synthetic_commit_then_retire(self):
        self.f.simulate();await self.prepare();r=await self.action('dispatch')
        self.assertEqual(r['journal']['state'],'OBSERVED');self.assertEqual(self.f.nums()['document_apply_events'],1)
        r=await self.action('retire');self.assertEqual(r['journal']['state'],'RETIRED');self.assertEqual(self.f.nums()['document_apply_nonces'],1)
    async def test_dispatch_cannot_replay(self):
        self.f.simulate();await self.prepare();await self.action('dispatch')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):await self.action('dispatch')
        self.assertEqual(self.f.nums()['document_apply_nonces'],1)
    async def test_inquiry_never_calls_core(self):
        self.f.simulate();await self.prepare();await self.action('dispatch');n=self.f.port.calls;self.f.app._core=None
        r=await self.action('inquire');self.assertEqual(r['journal']['operationState'],'OBSERVED_APPLICATION_RECORD');self.assertEqual(self.f.port.calls,n)
    async def test_unknown_other_id_rejected(self):
        await self.prepare();self.f.j.dispatch(self.f.j.current.digest);await self.observe()
        with self.assertRaisesRegex(Exception,'ORIGINAL_OPERATION_REQUIRED'):await self.call('inquire',operationId='a'*32,expectedApplyRevision=0,intentDigest=self.f.j.current.digest)
    async def test_inquire_without_digest_recovers_prepare(self):
        await self.prepare();r=await self.call('inquire',operationId='6f'*16,expectedApplyRevision=0,intentDigest=None)
        self.assertEqual(r['journal']['state'],'PREPARED');self.assertEqual(r['journal']['operationState'],'NOT_OBSERVED')
    async def test_new_id_cannot_bypass_dispatch(self):
        await self.prepare();self.f.j.dispatch(self.f.j.current.digest);await self.observe()
        with self.assertRaisesRegex(Exception,'ACTIVE_INTENT'):await self.call('prepare',operationId='a'*32,expectedApplyRevision=0,targetDigest=self.o.context(self.ch)['document']['targetDigest'])
    async def test_abandon_only_prepared(self):
        await self.prepare();r=await self.action('abandon');self.assertEqual(r['journal']['state'],'ABANDONED');self.assertEqual(self.f.port.calls,0)
    async def test_no_abandon_after_dispatch(self):
        await self.prepare();self.f.j.dispatch(self.f.j.current.digest);await self.observe()
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):await self.action('abandon')
    async def test_authority_revoked_before_request(self):
        with patch.object(self.f.c,'_guard',side_effect=RuntimeError('revoked')):
            with self.assertRaises(Exception):await self.prepare()
        self.assertEqual(self.f.j.status()['state'],'EMPTY')
    async def test_generation_change_before_send(self):
        self.f.gen[0]+=1
        with self.assertRaisesRegex(Exception,'STALE_GENERATION'):await self.prepare()
    async def test_cancel_queued_before_prepare(self):
        fut=self.o.request(self.ch,'prepare',{'context':self.o.context(self.ch),'expectedRevision':self.s['observation']['revision'],'operationId':'6f'*16,'expectedApplyRevision':0,'targetDigest':self.o.context(self.ch)['document']['targetDigest']});fut.cancel()
        with self.assertRaises(asyncio.CancelledError):await fut
        await asyncio.sleep(0);self.assertEqual(self.f.j.status()['state'],'EMPTY');self.assertEqual(self.o.stats()['inflight'],0)
    async def test_cancel_after_prepare_is_not_rollback(self):
        def cancel(stage):
            if stage=='journal.before_return':self.fut.cancel()
        self.f.j.observer=cancel
        self.fut=self.o.request(self.ch,'prepare',{'context':self.o.context(self.ch),'expectedRevision':self.s['observation']['revision'],'operationId':'6f'*16,'expectedApplyRevision':0,'targetDigest':self.o.context(self.ch)['document']['targetDigest']})
        with self.assertRaises(asyncio.CancelledError):await self.fut
        self.assertEqual(self.f.j.status()['state'],'PREPARED')
    async def test_commit_response_loss_preserves_original(self):
        self.f.simulate();await self.prepare()
        def lose(stage):
            if stage=='apply.after_commit':raise RuntimeError('lost response')
        self.f.app.observer=lose;r=await self.action('dispatch');self.assertEqual(r['journal']['operationState'],'OUTCOME_UNKNOWN');self.assertEqual(r['intent']['operationId'],'6f'*16)
    async def test_pin_failure_never_applies(self):
        self.f.simulate();await self.prepare()
        with patch.object(self.anchor,'advance',side_effect=OSError('pin unavailable')):
            with self.assertRaisesRegex(Exception,'PERSISTENCE_UNKNOWN'):await self.action('dispatch')
        self.assertEqual(self.f.port.calls,0)
    async def test_close_drains_without_closing_embedding_store(self):
        await self.o.close();self.assertTrue(self.o.stats()['cleanupComplete']);self.assertEqual(self.f.j.status()['state'],'EMPTY')
    async def test_reattach_requires_fresh_observation(self):
        await self.prepare();old=self.s['observation']['revision'];dg=self.f.j.current.digest
        self.o.detach(self.ch);self.ch=self.o.attach(allow_apply=True)
        with self.assertRaisesRegex(Exception,'STALE_OBSERVATION'):
            await self.call('dispatch',operationId='6f'*16,expectedApplyRevision=0,intentDigest=dg,expectedRevision=old)
    async def test_cancel_after_commit_retains_receipt(self):
        self.f.simulate();await self.prepare()
        def cancel(stage):
            if stage=='apply.after_commit':self.fut.cancel()
        self.f.app.observer=cancel
        self.fut=self.o.request(self.ch,'dispatch',{'context':self.o.context(self.ch),'expectedRevision':self.s['observation']['revision'],'operationId':'6f'*16,'expectedApplyRevision':0,'intentDigest':self.f.j.current.digest})
        with self.assertRaises(asyncio.CancelledError):await self.fut
        self.assertEqual(self.f.nums()['document_apply_events'],1);self.assertEqual(self.f.j.status()['state'],'OBSERVED')
        await self.observe();r=await self.action('inquire');self.assertEqual(r['journal']['state'],'OBSERVED');self.assertEqual(self.f.nums()['document_apply_nonces'],1)
    async def test_generation_change_during_prepare_no_old_success(self):
        def change(stage):
            if stage=='journal.before_return':self.f.gen[0]+=1
        self.f.j.observer=change
        with self.assertRaisesRegex(Exception,'STALE_GENERATION'):await self.prepare()
        self.assertEqual(self.f.j.status()['state'],'PREPARED')
