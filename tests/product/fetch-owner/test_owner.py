"""Real Inbox/TLS tests of the owner, not a new crypto implementation."""
import asyncio,copy,importlib,importlib.util,json,unittest
from pathlib import Path
from fetch_support import AsyncFixture
from par_crypto import objects
from product.wp10.events import EventError

class OwnerTests(AsyncFixture,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await AsyncFixture.asyncSetUp(self)
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_fetch_owner'), 'owner port missing')
        self.owner_module=importlib.import_module('product.wp09.par_fetch_owner')
        self.a,self.b=self.remote.chain();self.local.box.receive(*self.b)
        self.targets=[objects.envelope_id(self.b[0])];self.host=self.make()
        self.ch=self.host.attach(allow_fetch=True);self.ctx=self.host.context(self.ch)
    def make(self):
        (self.root/'plans').mkdir(mode=0o700,exist_ok=True)
        return self.owner_module.FetchOwner(self.make_plan(),self.local.source,self.targets,lambda:self.gen[0],self.session,self.root/'plans')
    async def asyncTearDown(self):
        if hasattr(self,'host'):await self.host.close()
        await AsyncFixture.asyncTearDown(self)
    async def call(self,op,**kw):
        return await self.host.request(self.ch,op,{'context':copy.deepcopy(self.ctx),**kw})
    async def observed(self):return await self.call('observe')
    async def proposed(self):
        v=await self.observed();return await self.call('propose',expectedRevision=v['observation']['revision'])
    async def accepted(self):
        v=await self.proposed();return await self.call('accept',expectedRevision=v['observation']['revision'],proposalId=v['proposal']['id'])
    async def test_observe_no_automatic_network_or_apply(self):
        before=self.local.box.pin();v=await self.observed();self.assertEqual(v['observation']['records'][0]['state'],'WAITING_DEPENDENCIES');self.assertEqual(before,self.local.box.pin());self.assertFalse(v['observation']['applied']);self.assertNotIn('apply',v['operations'])
    async def test_propose_only_then_accept_persists_without_get(self):
        v=await self.proposed();self.assertEqual(v['proposal']['records'],1);self.assertEqual(self.local.box.usage()['records'],1)
        r=await self.call('accept',expectedRevision=v['observation']['revision'],proposalId=v['proposal']['id']);self.assertEqual(self.local.box.usage()['records'],1);self.assertTrue(list((self.root/'plans').glob('*.cbor')));self.assertEqual(r['selection']['planDigest'],v['proposal']['planDigest'])
    async def test_fetch_selected_then_validate_core_blocked(self):
        a=await self.accepted();v=await self.call('fetch',expectedRevision=a['observation']['revision'],planDigest=a['selection']['planDigest']);self.assertEqual(v['progress']['stored'],1);self.assertEqual(self.local.box.usage()['records'],2)
        v=await self.call('validate',expectedRevision=v['observation']['revision']);self.assertEqual(v['observation']['records'][0]['validation']['reason'],'CORE_UNAVAILABLE');self.assertFalse(v['observation']['applied'])
    async def test_wrong_context_rejected(self):
        wrong=copy.deepcopy(self.ctx);wrong['planDigest']='0'*64
        with self.assertRaisesRegex(EventError,'OWNER_CONTEXT'):await self.host.request(self.ch,'observe',{'context':wrong})
    async def test_stale_revision_rejected(self):
        a=await self.observed();await self.observed()
        with self.assertRaisesRegex(EventError,'STALE_OBSERVATION'):await self.call('validate',expectedRevision=a['observation']['revision'])
    async def test_local_change_rejects_accept(self):
        p=await self.proposed();self.local.box.receive(*self.a)
        with self.assertRaisesRegex(EventError,'LOCAL_VIEW_CHANGED'):await self.call('accept',expectedRevision=p['observation']['revision'],proposalId=p['proposal']['id'])
    async def test_proposal_once_consumed(self):
        p=await self.proposed();a=await self.call('accept',expectedRevision=p['observation']['revision'],proposalId=p['proposal']['id'])
        with self.assertRaisesRegex(EventError,'PROPOSAL_UNAVAILABLE'):await self.call('accept',expectedRevision=a['observation']['revision'],proposalId=p['proposal']['id'])
    async def test_wrong_proposal_not_accepted(self):
        p=await self.proposed()
        with self.assertRaisesRegex(EventError,'PROPOSAL_UNAVAILABLE'):await self.call('accept',expectedRevision=p['observation']['revision'],proposalId='0'*64)
    async def test_default_grant_read_only(self):
        self.host.detach(self.ch);self.ch=self.host.attach();self.ctx=self.host.context(self.ch);v=await self.observed()
        with self.assertRaisesRegex(EventError,'OWNER_OPERATION_DENIED'):await self.call('propose',expectedRevision=v['observation']['revision'])
    async def test_apply_denied_even_full_grant(self):
        with self.assertRaisesRegex(EventError,'OWNER_OPERATION_DENIED'):await self.call('apply')
    async def test_generation_change_rejected(self):
        self.gen[0]+=1
        with self.assertRaisesRegex(EventError,'STALE_GENERATION'):await self.observed()
    async def test_input_copy_before_task_runs(self):
        args={'context':copy.deepcopy(self.ctx)};f=self.host.request(self.ch,'observe',args);args['context']['planDigest']='0'*64;self.assertEqual((await f)['observation']['pin'],self.ctx)
    async def test_extra_field_rejected(self):
        with self.assertRaisesRegex(EventError,'OWNER_SCHEMA'):await self.call('observe',path='/tmp/other')
    async def test_single_worker_no_implicit_queue(self):
        f=self.host.request(self.ch,'observe',{'context':self.ctx})
        with self.assertRaisesRegex(EventError,'OWNER_BUSY'):self.host.request(self.ch,'observe',{'context':self.ctx})
        await f
    async def test_cancel_before_start_no_proposal_or_io(self):
        v=await self.observed();f=self.host.request(self.ch,'propose',{'context':self.ctx,'expectedRevision':v['observation']['revision']});f.cancel();await asyncio.sleep(0);await asyncio.sleep(0)
        v=await self.observed();self.assertIsNone(v['proposal']);self.assertEqual(self.local.box.usage()['records'],1)
    async def test_restart_resume_plan_digest_without_refetch(self):
        a=await self.accepted();p=a['selection']['planDigest'];v=await self.call('fetch',expectedRevision=a['observation']['revision'],planDigest=p)
        await self.host.close();self.host=self.make();self.ch=self.host.attach(allow_fetch=True);self.ctx=self.host.context(self.ch);v=await self.observed()
        r=await self.call('resume',expectedRevision=v['observation']['revision'],planDigest=p);self.assertEqual(r['progress']['stored'],1);self.assertFalse(r['observation']['applied'])
    async def test_resume_wrong_sha_rejected(self):
        await self.accepted();v=await self.observed()
        with self.assertRaisesRegex(EventError,'METADATA_READ_FAILED'):await self.call('resume',expectedRevision=v['observation']['revision'],planDigest='0'*64)
    async def test_resume_corrupt_plan_rejected(self):
        a=await self.accepted();p=a['selection']['planDigest'];path=self.root/'plans'/(p+'.cbor');path.write_bytes(b'bad');v=await self.observed()
        with self.assertRaisesRegex(EventError,'METADATA_PIN'):await self.call('resume',expectedRevision=v['observation']['revision'],planDigest=p)
    async def test_resume_wrong_targets_rejected(self):
        a=await self.accepted();p=a['selection']['planDigest'];await self.host.close();self.targets=[objects.envelope_id(self.a[0])];self.host=self.make();self.ch=self.host.attach(allow_fetch=True);self.ctx=self.host.context(self.ch);v=await self.observed()
        with self.assertRaises(EventError):await self.call('resume',expectedRevision=v['observation']['revision'],planDigest=p)
    async def test_fetch_wrong_plan_rejected(self):
        a=await self.accepted()
        with self.assertRaisesRegex(EventError,'PLAN_SELECTION'):await self.call('fetch',expectedRevision=a['observation']['revision'],planDigest='0'*64)
    async def test_missing_expected_revision_rejected(self):
        with self.assertRaisesRegex(EventError,'OWNER_SCHEMA'):await self.call('validate')
    async def test_timeout_invalid_rejected(self):
        v=await self.observed()
        for t in [True,0,120001,1.5]:
            with self.assertRaisesRegex(EventError,'HOST_INPUT_INVALID' if type(t)is float else 'OWNER_SCHEMA'):await self.call('propose',expectedRevision=v['observation']['revision'],timeoutMs=t)
    async def test_inquiry_unavailable_not_absent(self):
        v=await self.observed();v=await self.call('inquire',expectedRevision=v['observation']['revision'],operationId='a'*32,expectedApplyRevision=0);self.assertEqual(v['observation']['operation']['state'],'INQUIRY_FAILED')
    async def test_detached_channel_cannot_write(self):
        self.host.detach(self.ch)
        with self.assertRaisesRegex(EventError,'OWNER_CHANNEL'):await self.observed()
    async def test_no_certificate_or_payload_in_snapshot(self):
        s=json.dumps(await self.accepted());self.assertNotIn('PUBLIC OPAQUE',s);self.assertNotIn('certificate',s.lower());self.assertNotIn('key',s.lower())
    async def test_connection_limit(self):
        with self.assertRaisesRegex(EventError,'OWNER_CHANNEL_LIMIT'):self.host.attach(allow_fetch=True)
    async def test_close_command_no_more_requests(self):
        r=await self.call('close');self.assertTrue(r['closed'])
        with self.assertRaisesRegex(EventError,'OWNER_CHANNEL'):await self.observed()
