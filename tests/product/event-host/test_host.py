"""Actual journal, one owner event loop; no synthetic event engine."""
import asyncio
import importlib
import threading
import unittest
from test_events import EventTest

class HostSupport(EventTest):
    def run_async(self, body, **limits):
        self.create()
        async def run():
            try: module=importlib.import_module('product.wp10.host')
            except ModuleNotFoundError: module=None
            self.assertIsNotNone(module, 'bounded asynchronous owner event host is not implemented')
            host=module.EventHost(self.journal, **limits)
            try: await body(host)
            finally: host.close()
        asyncio.run(run())
    async def opened(self,h, consumer=b'c'*16):
        c=h.attach(consumer);r=await h.request(c,'open',{'context':h.context(c),'expectedCursor':None})
        return c,r['result']['sessionId']
    async def poll(self,h,c,s):
        return await h.request(c,'poll',{'sessionId':s,'limit':16,'byteLimit':262144})
    async def reject_async(self,code,f):
        with self.assertRaises(Exception) as cm: await f
        self.assertEqual(getattr(cm.exception,'code',None),code)
class HostTests(HostSupport):
    def test_empty_poll_publish_before_wait_does_not_lose_wakeup(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);self.assertEqual(a['result']['events'],[])
            h.publish((1).to_bytes(16,'big'),{'body':'between','count':2**64-1})
            w=await asyncio.wait_for(h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']}),1)
            self.assertEqual(w['result']['reason'],'changed')
            b=await self.poll(h,c,s);self.assertEqual(b['result']['events'][0]['payload']['body']['value'],'between')
            self.assertEqual(b['result']['cursor']['position'],'0')
        self.run_async(body)
    def test_waiter_woken_after_registration(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.01)
            self.assertEqual(h.stats()['waiters'],1)
            h.publish((1).to_bytes(16,'big'),{'body':'after','count':1})
            self.assertEqual((await asyncio.wait_for(f,1))['result']['reason'],'changed')
            self.assertEqual(h.stats()['waiters'],0)
        self.run_async(body)
    def test_ack_only_advances_on_explicit_request(self):
        async def body(h):
            self.emit();c,s=await self.opened(h);a=await self.poll(h,c,s)
            self.assertEqual((await self.poll(h,c,s))['result'],a['result'])
            r=await h.request(c,'ack',{'sessionId':s,'token':a['result']['ackToken']})
            self.assertEqual(r['result']['cursor']['position'],'1')
        self.run_async(body)
    def test_direct_owner_publish_detected_by_wait_audit(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            self.emit();w=await asyncio.wait_for(f,1);self.assertEqual(w['result']['reason'],'changed')
        self.run_async(body,heartbeat_seconds=.02)
    def test_authority_change_wakes_empty_wait(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            self.same_epoch();w=await asyncio.wait_for(f,1);self.assertEqual(w['result']['reason'],'changed')
        self.run_async(body,heartbeat_seconds=.02)
    def test_cancel_wait_releases_slot_without_ack(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            r=await h.request(c,'cancel',{'sessionId':s})
            self.assertEqual(r['result']['kind'],'cancelled')
            await self.reject_async('SUBSCRIPTION_CLOSED',f)
            self.assertEqual(h.stats()['waiters'],0)
            h.detach(c);c,s=await self.opened(h)
            self.assertEqual((await self.poll(h,c,s))['result']['cursor']['position'],'0')
        self.run_async(body)
    def test_cancelled_queued_open_does_not_create_consumer(self):
        async def body(h):
            c=h.attach(b'c'*16);f=h.request(c,'open',{'context':h.context(c),'expectedCursor':None});f.cancel()
            await asyncio.sleep(.01);self.assertEqual(self.journal.inspect()['consumers'],0)
            self.assertEqual(h.stats()['requests'],0)
        self.run_async(body)
    def test_queue_full_is_rejection_not_unbounded_wait(self):
        async def body(h):
            a=h.attach(b'a'*16);b=h.attach(b'b'*16)
            f=h.request(a,'open',{'context':h.context(a),'expectedCursor':None})
            self.rejects('HOST_QUEUE_FULL',lambda:h.request(b,'open',{'context':h.context(b),'expectedCursor':None}))
            await f;self.assertEqual(h.stats()['requests'],0)
        self.run_async(body,max_requests=1)
    def test_cleanup_has_reserved_capacity(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            await h.request(c,'cancel',{'sessionId':s});await self.reject_async('SUBSCRIPTION_CLOSED',f)
        self.run_async(body,max_requests=1)
    def test_one_ordinary_request_per_channel(self):
        async def body(h):
            c,s=await self.opened(h);a=h.request(c,'poll',{'sessionId':s,'limit':1,'byteLimit':1024})
            self.rejects('HOST_CHANNEL_BUSY',lambda:h.request(c,'cursor',{'sessionId':s}));await a
        self.run_async(body)
    def test_wait_does_not_block_other_channel(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            d,t=await self.opened(h,b'd'*16);await self.poll(h,d,t)
            self.assertFalse(f.done());f.cancel();await asyncio.sleep(0)
        self.run_async(body)
    def test_stale_incarnation_ticket_rejected(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);ticket=dict(a['ticket']);ticket['hostId']='00'*16
            await self.reject_async('WAKE_TICKET_INVALID',h.request(c,'wait',{'sessionId':s,'ticket':ticket}))
        self.run_async(body)
    def test_future_revision_ticket_rejected(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);ticket=dict(a['ticket']);ticket['revision']='999'
            await self.reject_async('WAKE_TICKET_INVALID',h.request(c,'wait',{'sessionId':s,'ticket':ticket}))
        self.run_async(body)
    def test_wait_requires_empty_poll(self):
        async def body(h):
            self.emit();c,s=await self.opened(h);a=await self.poll(h,c,s)
            await self.reject_async('WAKE_TICKET_INVALID',h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']}))
        self.run_async(body)
    def test_timeout_is_hint_not_end_of_stream(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            r=await asyncio.wait_for(h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']}),1)
            self.assertEqual(r['result']['reason'],'deadline');self.assertEqual((await self.poll(h,c,s))['result']['events'],[])
        self.run_async(body,wait_seconds=.03,heartbeat_seconds=.01)
    def test_turn_budget_yields_to_other_callbacks(self):
        async def body(h):
            order=[];fs=[]
            for i in range(4):
                c=h.attach(bytes([i+1])*16);fs.append(h.request(c,'open',{'context':h.context(c),'expectedCursor':None}))
            asyncio.get_running_loop().call_soon(lambda:order.append(sum(f.done() for f in fs)))
            await asyncio.gather(*fs);self.assertEqual(order,[1])
        self.run_async(body,turn_budget=1)
    def test_bad_operation_does_not_create_work(self):
        async def body(h):
            c=h.attach(b'c'*16);self.rejects('HOST_OPERATION_DENIED',lambda:h.request(c,'publish',{}));self.assertEqual(h.stats()['requests'],0)
        self.run_async(body)
    def test_large_request_refused_before_retention(self):
        async def body(h):
            c=h.attach(b'c'*16);self.rejects('HOST_INPUT_INVALID',lambda:h.request(c,'open',{'x':'x'*70000}));self.assertEqual(h.stats()['request_bytes'],0)
        self.run_async(body)
    def test_plain_object_input_only(self):
        class Bad(dict): pass
        async def body(h):
            c=h.attach(b'c'*16);self.rejects('HOST_INPUT_INVALID',lambda:h.request(c,'open',Bad()))
        self.run_async(body)
    def test_request_snapshot_not_caller_mutation(self):
        async def body(h):
            c=h.attach(b'c'*16);r={'context':h.context(c),'expectedCursor':None};f=h.request(c,'open',r);r['context']['epoch']='9'
            self.assertEqual((await f)['result']['context']['epoch'],'1')
        self.run_async(body)
    def test_wrong_thread_rejected_before_queue_mutation(self):
        async def body(h):
            errors=[]
            def run():
                try:h.attach(b'c'*16)
                except Exception as e:errors.append(e.code)
            t=threading.Thread(target=run);t.start();t.join();self.assertEqual(errors,['WRONG_OWNER']);self.assertEqual(h.stats()['channels'],0)
        self.run_async(body)
    def test_channel_limit(self):
        async def body(h):
            h.attach(b'a'*16);self.rejects('HOST_CHANNEL_LIMIT',lambda:h.attach(b'b'*16))
        self.run_async(body,max_channels=1)
    def test_detach_cancels_pending_and_does_not_ack(self):
        async def body(h):
            self.emit();c,s=await self.opened(h);await self.poll(h,c,s);h.detach(c)
            c,s=await self.opened(h);self.assertEqual((await self.poll(h,c,s))['result']['events'][0]['sequence'],'1')
        self.run_async(body)
    def test_closed_host_refuses_work(self):
        async def body(h):
            h.close();self.rejects('HOST_CLOSED',lambda:h.attach(b'c'*16));self.assertEqual(self.journal.inspect()['events'],0)
        self.run_async(body)
    def test_revoke_pending_delivery_rejects_ack(self):
        async def body(h):
            self.emit();c,s=await self.opened(h);a=await self.poll(h,c,s);self.same_epoch()
            await self.reject_async('AUTHORITY_CHANGED',h.request(c,'ack',{'sessionId':s,'token':a['result']['ackToken']}))
            self.assertEqual((await h.request(c,'cursor',{'sessionId':s}))['result']['cursor']['position'],'0')
        self.run_async(body)
    def test_journal_corruption_wakes_waiter_with_failure(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            self.journal._connection.execute("UPDATE metadata SET seal=x'00'")
            await self.reject_async('JOURNAL_CORRUPT',asyncio.wait_for(f,1));self.assertEqual(h.stats()['state'],'FAILED')
        self.run_async(body,heartbeat_seconds=.02)
    def test_heartbeat_does_not_run_without_waiters(self):
        async def body(h):
            before=h.stats()['observations'];await asyncio.sleep(.05);self.assertEqual(h.stats()['observations'],before)
        self.run_async(body,heartbeat_seconds=.01)
