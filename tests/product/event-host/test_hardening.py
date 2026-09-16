import asyncio,os,signal,threading
from test_host import HostSupport

class HardeningTests(HostSupport):
    def test_publish_between_empty_poll_and_ticket_does_not_hide_event(self):
        async def body(h):
            c,s=await self.opened(h);port=h._channels[c].port;original=port.poll
            def between(r):
                value=original(r);self.emit();return value
            port.poll=between
            a=await self.poll(h,c,s);self.assertEqual(a['result']['events'],[])
            w=await asyncio.wait_for(h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']}),.3)
            self.assertEqual(w['result']['reason'],'changed')
        self.run_async(body)
    def test_publish_postcheck_failure_does_not_report_success(self):
        async def body(h):
            original=h._observe
            def corrupt():
                self.journal._connection.execute("UPDATE metadata SET seal=x'00'")
                return original()
            h._observe=corrupt
            self.rejects('EVENT_OUTCOME_UNKNOWN',lambda:h.publish(b'o'*16,{'body':'written','count':1}))
            self.assertEqual(h.stats()['state'],'FAILED')
        self.run_async(body)
    def test_failed_host_still_allows_subscription_cleanup(self):
        async def body(h):
            c,s=await self.opened(h);self.journal._connection.execute("UPDATE metadata SET seal=x'00'")
            self.rejects('JOURNAL_CORRUPT',h.notify)
            r=await h.request(c,'cancel',{'sessionId':s});self.assertEqual(r['result']['kind'],'cancelled')
            self.assertEqual(len(self.journal._subs),0)
        self.run_async(body)
    def test_wrong_session_cancel_does_not_kill_wait(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            await self.reject_async('SDK_SESSION_MISMATCH',h.request(c,'cancel',{'sessionId':'00'*16}))
            self.assertFalse(f.done());self.emit();await asyncio.wait_for(f,1)
        self.run_async(body,heartbeat_seconds=.02)
    def test_queue_byte_limit_before_consumer_effect(self):
        async def body(h):
            c=h.attach(b'c'*16)
            self.rejects('HOST_QUEUE_FULL',lambda:h.request(c,'open',{'padding':'x'*1500}))
            self.assertEqual(self.journal.inspect()['consumers'],0)
        self.run_async(body,max_request_bytes=1024)
    def test_future_cancelled_after_ack_commit_does_not_rollback(self):
        async def body(h):
            self.emit();c,s=await self.opened(h);a=await self.poll(h,c,s)
            f=None
            def drop(stage):
                if stage=='ack.after_commit':f.cancel()
            self.journal.observer=drop
            f=h.request(c,'ack',{'sessionId':s,'token':a['result']['ackToken']})
            with self.assertRaises(asyncio.CancelledError):await f
            self.journal.observer=None
            self.assertEqual((await h.request(c,'cursor',{'sessionId':s}))['result']['cursor']['position'],'1')
        self.run_async(body)
    def test_closed_host_drops_all_waits_timers_and_buffers(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s);f=h.request(c,'wait',{'sessionId':s,'ticket':a['ticket']});await asyncio.sleep(.005)
            h.close();await self.reject_async('HOST_CHANNEL_CLOSED',f)
            self.assertIsNone(h._heartbeat);self.assertEqual(h.stats()['request_bytes'],0);self.assertFalse(self.journal._subs)
        self.run_async(body)
    def test_fork_inherits_neither_owner_nor_host(self):
        async def body(h):
            r,w=os.pipe();pid=os.fork()
            if pid==0:
                os.close(r)
                try:h.stats();message=b'bad'
                except Exception as e:message=str(getattr(e,'code','unknown')).encode()
                os.write(w,message);os.close(w);os._exit(0)
            os.close(w);value=os.read(r,256);os.close(r);_,status=os.waitpid(pid,0)
            self.assertEqual(status,0);self.assertEqual(value,b'WRONG_OWNER')
        self.run_async(body)
    def test_returned_ticket_mutation_does_not_change_owner_checkpoint(self):
        async def body(h):
            c,s=await self.opened(h);a=await self.poll(h,c,s)
            original=dict(a['ticket'])
            a['ticket']['revision']='999'
            self.emit();h.notify()
            result=await asyncio.wait_for(h.request(c,'wait',{'sessionId':s,'ticket':original}),.3)
            self.assertEqual(result['result']['reason'],'changed')
            self.assertEqual((await h.request(c,'cursor',{'sessionId':s}))['result']['cursor']['position'],'0')
        self.run_async(body)
