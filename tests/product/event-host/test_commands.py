"""New command boundary: actual journal/authority, no mock durability."""
import asyncio, copy, importlib, threading
from test_events import EventTest
from product.wp10.host import EventHost, OPERATIONS

class CommandTests(EventTest):
    def setUp(self):
        super().setUp()
        try: self.commands = importlib.import_module('product.wp10.commands')
        except ModuleNotFoundError: self.commands = None
        self.assertTrue(self.commands is not None and hasattr(self.commands, 'EventCommandHost'),
                        'separate typed event command host is not implemented')
        self.create()

    def run_async(self, fn, **options):
        async def run():
            host = EventHost(self.journal, heartbeat_seconds=.02)
            commands = self.commands.EventCommandHost(host, **options)
            try: await fn(host, commands)
            finally:
                commands.close(); host.close()
                await commands.wait_closed()
        asyncio.run(run())

    def args(self, commands, channel, n=1):
        return {'context': commands.context(channel), 'operationId': n.to_bytes(16, 'big').hex(),
                'payload': {'body': {'kind':'text','value':'kept private'},
                            'count': {'kind':'uint64','value':'18446744073709551615'}}, 'parents': []}

    def inquiry(self, commands, channel, n=1):
        return {'context':commands.context(channel), 'operationId':n.to_bytes(16,'big').hex()}

    async def rejected(self, future, code):
        r = await future
        self.assertEqual(r['kind'], 'rejected'); self.assertEqual(r['code'], code)
        return r

    def test_publish_local_only_exact_integer(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);r=await c.request(ch,'publish',self.args(c,ch))
            self.assertEqual(r['kind'],'local-committed');self.assertEqual(r['sequence'],'1')
            self.assertFalse(r['replicated']);self.assertFalse(r['cancellationRequested'])
            e=self.journal.subscribe(b'z'*16).poll().events[0]
            self.assertEqual(self.events.decode_payload(e.payload)['count'],2**64-1)
        self.run_async(body)

    def test_same_id_same_input_does_not_reserve_again(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch)
            self.assertEqual(await c.request(ch,'publish',a),await c.request(ch,'publish',a))
            self.assertEqual(self.journal.inspect()['events'],1);self.assertEqual(self.journal.inspect()['nonces'],1)
        self.run_async(body)

    def test_same_id_changed_payload_is_rejected(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);await c.request(ch,'publish',a)
            a['payload']['body']['value']='different'
            await self.rejected(c.request(ch,'publish',a),'OPERATION_CONFLICT')
            self.assertEqual(self.journal.inspect()['nonces'],1)
        self.run_async(body)

    def test_inquiry_absence_is_read_only(self):
        async def body(h,c):
            ch=c.attach();r=await c.request(ch,'inquire',self.inquiry(c,ch))
            self.assertEqual(r['kind'],'not-found-local');self.assertEqual(self.journal.inspect()['nonces'],0)
            self.assertEqual(self.journal.inspect()['consumers'],0)
        self.run_async(body)

    def test_inquiry_recovers_committed_receipt(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);r=await c.request(ch,'publish',self.args(c,ch))
            self.assertEqual(await c.request(ch,'inquire',self.inquiry(c,ch)),r)
        self.run_async(body)

    def test_default_grant_refuses_publish_before_nonce(self):
        async def body(h,c):
            ch=c.attach();await self.rejected(c.request(ch,'publish',self.args(c,ch)),'COMMAND_NOT_AUTHORIZED')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_json_authority_cannot_escalate_grant(self):
        async def body(h,c):
            ch=c.attach();a=self.args(c,ch);a['context']['authority']='owner-publish'
            await self.rejected(c.request(ch,'publish',a),'COMMAND_CONTEXT_MISMATCH')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_wrong_protocol_refused_before_nonce(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['context']['protocol']='par-sdk-events-local-0038'
            await self.rejected(c.request(ch,'publish',a),'COMMAND_CONTEXT_MISMATCH')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_wrong_stream_context_refused(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['context']['streamId']='00'*32
            await self.rejected(c.request(ch,'publish',a),'COMMAND_CONTEXT_MISMATCH')
        self.run_async(body)

    def test_number_is_not_decimal_uint64(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['payload']['count']['value']=42
            await self.rejected(c.request(ch,'publish',a),'COMMAND_INPUT_INVALID')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_noncanonical_or_out_of_range_integers_refused(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True)
            for value in ['01','-1','18446744073709551616','1e2','+1','١']:
                a=self.args(c,ch);a['payload']['count']['value']=value
                await self.rejected(c.request(ch,'publish',a),'COMMAND_INPUT_INVALID')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_mismatched_field_kind_refused(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['payload']['count']={'kind':'bool','value':True}
            await self.rejected(c.request(ch,'publish',a),'COMMAND_INPUT_INVALID')
        self.run_async(body)

    def test_extra_field_refused_before_nonce(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['payload']['extra']={'kind':'text','value':'bad'}
            await self.rejected(c.request(ch,'publish',a),'COMMAND_INPUT_INVALID')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_large_payload_refused_before_nonce(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['payload']['body']['value']='x'*16385
            await self.rejected(c.request(ch,'publish',a),'RESOURCE_LIMIT')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_causal_parent_and_parent_conflict(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=await c.request(ch,'publish',self.args(c,ch))
            second=self.args(c,ch,2);second['parents']=[a['eventId']]
            self.assertEqual((await c.request(ch,'publish',second))['sequence'],'2')
            second['parents']=[];await self.rejected(c.request(ch,'publish',second),'OPERATION_CONFLICT')
        self.run_async(body)

    def test_missing_parent_refused(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['parents']=['aa'*32]
            await self.rejected(c.request(ch,'publish',a),'DEPENDENCIES_PENDING')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_queued_cancel_has_no_durable_effect(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);f=c.request(ch,'publish',self.args(c,ch));f.cancel()
            await asyncio.sleep(0);await asyncio.sleep(0)
            self.assertEqual(self.journal.inspect()['nonces'],0);self.assertEqual(c.stats()['requests'],0)
        self.run_async(body)

    def test_owner_cancel_after_nonce_keeps_reservation_not_event(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);f=c.request(ch,'publish',self.args(c,ch))
            self.journal.observer=lambda stage: f.cancel() if stage=='nonce.after_commit' else None
            with self.assertRaises(asyncio.CancelledError):await f
            self.journal.observer=None
            self.assertEqual(self.journal.inspect()['nonces'],1);self.assertEqual(self.journal.inspect()['events'],0)
            r=await c.request(ch,'publish',self.args(c,ch));self.assertEqual(r['sequence'],'1')
            self.assertEqual(self.journal.inspect()['nonces'],2)
        self.run_async(body)

    def test_owner_cancel_after_commit_does_not_rollback(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);f=c.request(ch,'publish',self.args(c,ch))
            self.journal.observer=lambda stage: f.cancel() if stage=='event.after_commit' else None
            with self.assertRaises(asyncio.CancelledError):await f
            self.journal.observer=None
            self.assertEqual(self.journal.inspect()['events'],1)
            self.assertEqual((await c.request(ch,'inquire',self.inquiry(c,ch)))['kind'],'local-committed')
        self.run_async(body)

    def test_publish_wakes_subscription_without_ack(self):
        async def body(h,c):
            sub=h.attach(b'c'*16);opened=await h.request(sub,'open',{'context':h.context(sub),'expectedCursor':None})
            sid=opened['result']['sessionId'];batch=await h.request(sub,'poll',{'sessionId':sid,'limit':16,'byteLimit':262144})
            wait=h.request(sub,'wait',{'sessionId':sid,'ticket':batch['ticket']});await asyncio.sleep(.001)
            ch=c.attach(allow_publish=True);await c.request(ch,'publish',self.args(c,ch))
            self.assertEqual((await wait)['result']['reason'],'changed')
            polled=await h.request(sub,'poll',{'sessionId':sid,'limit':16,'byteLimit':262144})
            self.assertEqual(polled['result']['cursor']['position'],'0');self.assertEqual(len(polled['result']['events']),1)
        self.run_async(body)

    def test_mutation_after_admission_cannot_change_payload(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);f=c.request(ch,'publish',a);a['payload']['body']['value']='mutated'
            await f;e=self.journal.subscribe(b'z'*16).poll().events[0]
            self.assertEqual(self.events.decode_payload(e.payload)['body'],'kept private')
        self.run_async(body)

    def test_one_request_per_command_connection(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);f=c.request(ch,'publish',self.args(c,ch))
            self.rejects('HOST_CHANNEL_BUSY',lambda:c.request(ch,'inquire',self.inquiry(c,ch)));await f
        self.run_async(body)

    def test_global_queue_limit_rejects_without_wait(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);other=c.attach();f=c.request(ch,'publish',self.args(c,ch))
            self.rejects('HOST_QUEUE_FULL',lambda:c.request(other,'inquire',self.inquiry(c,other)));await f
            self.assertEqual(c.stats()['requests'],0)
        self.run_async(body,max_requests=1)

    def test_byte_budget_rejects_before_effect(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);a['payload']['body']['value']='x'*1500
            self.rejects('HOST_QUEUE_FULL',lambda:c.request(ch,'publish',a))
            self.assertEqual(self.journal.inspect()['nonces'],0);self.assertEqual(c.stats()['request_bytes'],0)
        self.run_async(body,max_request_bytes=1024)

    def test_detach_releases_queued_input(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);f=c.request(ch,'publish',self.args(c,ch));c.detach(ch)
            with self.assertRaises(self.events.EventError):await f
            await asyncio.sleep(0);self.assertEqual(c.stats()['requests'],0);self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_parent_close_refuses_commands(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);h.close()
            self.rejects('HOST_CLOSED',lambda:c.request(ch,'publish',self.args(c,ch)))
            await c.wait_closed();self.assertEqual(c.stats()['channels'],0)
        self.run_async(body)

    def test_command_context_is_copied(self):
        async def body(h,c):
            ch=c.attach();ctx=c.context(ch);ctx['schema']['count']='text'
            self.assertEqual(c.context(ch)['schema']['count'],'uint64')
        self.run_async(body)

    def test_reader_cannot_mint_writer_permission(self):
        self.close_journal();import shutil;shutil.rmtree(self.path)
        d=self.s.devices[1];self.create(certificate=d['cert'],sign_seed=d['seed'])
        async def body(h,c):
            ch=c.attach(allow_publish=True);await self.rejected(c.request(ch,'publish',self.args(c,ch)),'NOT_AUTHORIZED')
            self.assertEqual(self.journal.inspect()['nonces'],0)
        self.run_async(body)

    def test_wrong_thread_refused_before_retention(self):
        async def body(h,c):
            ch=c.attach(allow_publish=True);a=self.args(c,ch);out=[]
            def other():
                try:c.request(ch,'publish',a)
                except self.events.EventError as e:out.append(e.code)
            t=threading.Thread(target=other);t.start();t.join(2)
            self.assertEqual(out,['WRONG_OWNER']);self.assertEqual(c.stats()['requests'],0)
        self.run_async(body)

    def test_subscription_operation_set_is_unchanged(self):
        async def body(h,c):
            self.assertEqual(OPERATIONS,{'open','poll','ack','cursor','cancel','wait'})
            ch=h.attach(b'c'*16);self.rejects('HOST_OPERATION_DENIED',lambda:h.request(ch,'publish',{}))
        self.run_async(body)
