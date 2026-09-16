import socket,time,selectors
from scheduler_support import SchedulerTest,h
from par_keeper_service.transport import send,receive,frame
class SchedulerTransfer(SchedulerTest):
    def prime_get(self,*,largest=False,send_buffer=None,**kw):
        self.ready_keeper();self.start_host(**kw);self.submit_close();s,hello=self.connect()
        if send_buffer is not None:
            for c in self.host.read.connections.values():c.socket.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,send_buffer)
        payload=max(self.bundle.objects,key=lambda k:len(self.bundle.objects[k])) if largest else None
        raw=self.request_raw(hello,payload=payload);send(s,raw,65536,time.monotonic()+1);self.tick(2)
        self.assertEqual(len(self.keeper._pins),1)
        return s,hello,raw
    def test_pinned_response_keeps_prepared_job_waiting(self):
        s,_,_=self.prime_get(send_chunk=1);self.host.schedule(self.jid());self.tick(3)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED');self.assertEqual(self.window.phase,'OPEN');self.assertEqual(self.host.diagnostics()['waiting_reason'],'ACTIVE_TRANSFERS')
    def test_normal_response_releases_pin_before_effect(self):
        # Force backpressure: never assume every response fits a Unix socket buffer.
        s,hello,raw=self.prime_get(send_chunk=65536,largest=True,send_buffer=4096)
        self.host.schedule(self.jid());self.tick(5)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED')
        self.assertEqual(len(self.keeper._pins),1);self.assertEqual(self.host.effect_steps,0)
        s.setblocking(False);data=bytearray();limit=time.monotonic()+4
        while time.monotonic()<limit:
            self.host.tick(.001)
            while True:
                try:b=s.recv(65536)
                except BlockingIOError:break
                if not b:break
                data.extend(b);self.assertLessEqual(len(data),1048580)
            if len(data)>=4:
                want=int.from_bytes(data[:4],'big');self.assertTrue(1<=want<=1048576)
                if len(data)==4+want and self.host.jobs.poll(self.jid())['state']=='SUCCEEDED':break
        self.assertEqual(len(data),4+int.from_bytes(data[:4],'big'))
        expected=self.bundle.objects[max(self.bundle.objects,key=lambda k:len(self.bundle.objects[k]))]
        self.assertEqual(self.ipc.check_response(self.p,self.kp,hello,raw,bytes(data[4:])),expected)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED')
        self.assertEqual(len(self.keeper._pins),0);self.assertEqual(self.window.phase,'CLOSED')
    def test_disconnect_releases_pin_before_effect(self):
        s,_,_=self.prime_get(send_chunk=1);self.host.schedule(self.jid());self.tick(2);s.close();self.complete()
        self.assertEqual(len(self.keeper._pins),0);self.assertGreater(self.host.read.counts['dropped'],0)
    def test_timeout_releases_pin_before_effect(self):
        s,_,_=self.prime_get(send_chunk=1,deadline_ms=50);self.host.schedule(self.jid());time.sleep(.08);self.complete()
        self.assertEqual(len(self.keeper._pins),0);self.assertGreater(self.host.read.counts['expired'],0)
    def test_partial_request_blocks_until_disconnect(self):
        self.start_host();self.submit_close();s,hello=self.connect(True);raw=frame(self.host_request(hello),65536);s.sendall(raw[:7]);self.tick(2)
        self.host.schedule(self.jid());self.tick(3);self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED');s.close();self.complete()
    def test_hello_only_socket_is_not_idle(self):
        self.start_host();self.submit_close();s,hello=self.connect();self.host.schedule(self.jid());self.tick(3)
        self.assertEqual(self.host.diagnostics()['activity']['connections'],1);self.assertEqual(self.window.phase,'OPEN');s.close();self.complete()
    def test_backlog_is_not_admitted_while_paused(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid())
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(.05);s.connect(str(self.upload_path));self.sockets.append(s);self.tick(2)
        self.assertEqual(len(self.host.upload.connections),0)
        with self.assertRaises(socket.timeout):s.recv(1)
        self.complete();self.tick(2);hello=receive(s,4096,time.monotonic()+1)
        self.assertEqual(self.hp.check_hello(self.p,self.kp,self.store_id,self.grant,hello)[11],'CLOSED')
    def test_cancel_drain_preserves_existing_connection(self):
        self.start_host();self.submit_close();s,hello=self.connect();self.host.schedule(self.jid());self.tick(2);self.host.cancel(self.jid())
        self.assertEqual(self.host.diagnostics()['mode'],'SERVING');self.assertEqual(len(self.host.read.connections),1);self.assertEqual(self.window.phase,'OPEN')
    def test_drain_timeout_does_not_force_effect(self):
        self.start_host(drain_timeout=.05,deadline_ms=5000);self.submit_close();self.connect();self.host.schedule(self.jid());time.sleep(.07);self.tick()
        self.assertEqual(self.host.diagnostics()['fault'],'DRAIN_TIMEOUT');self.assertEqual(self.window.phase,'OPEN');self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED')
        self.host.cancel(self.jid());self.assertTrue(self.host.read.accepting)
    def test_pending_reader_without_connection_blocks_effect(self):
        self.ready_keeper();self.start_host();self.submit_close();from par_keeper import make_call
        oid=sorted(self.bundle.objects)[0];q=make_call(self.p,self.cs,self.cap,'get',self.lid,h('local-pin'),oid)
        with self.keeper.reader(self.lid,oid,self.cap,q):
            self.host.schedule(self.jid());self.tick(3);self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED')
        self.complete()
    def test_authority_change_during_response_drops_pin_and_holds_job(self):
        s,_,_=self.prime_get(send_chunk=1);self.host.schedule(self.jid());self.tick(2);self.change_authority()
        self.err('STALE_AUTHORITY',lambda:self.tick());self.assertEqual(len(self.keeper._pins),0);self.assertEqual(self.window.phase,'OPEN');self.assertFalse(self.host.read.accepting)
    def test_invalid_read_request_does_not_keep_activity(self):
        self.start_host();self.submit_close();s,hello=self.connect();s.sendall((65537).to_bytes(4,'big'));self.host.schedule(self.jid());self.complete();self.assertEqual(len(self.host.read.connections),0)
    def test_two_endpoints_are_polled_in_alternating_order(self):
        self.start_host();seen=[]
        from unittest.mock import patch
        with patch.object(self.host.read,'poll',side_effect=lambda t:seen.append('read')),patch.object(self.host.upload,'poll',side_effect=lambda t:seen.append('upload')):
            self.tick(2)
        self.assertEqual(seen,['read','upload','upload','read'])
    def test_one_response_failure_does_not_fake_idle_on_other_endpoint(self):
        self.start_host();self.submit_close();a,_=self.connect();b,_=self.connect(True);self.host.schedule(self.jid());a.close();self.tick(3)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED');self.assertEqual(self.host.activity.snapshot()['upload_connections'],1);b.close();self.complete()
