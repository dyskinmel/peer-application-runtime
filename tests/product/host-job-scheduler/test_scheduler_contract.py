import os,selectors,socket,threading
from scheduler_support import SchedulerTest,h
class SchedulerContract(SchedulerTest):
    def test_starts_serving_without_selecting_job(self):
        self.start_host();d=self.host.diagnostics();self.assertEqual(d['mode'],'SERVING');self.assertIsNone(d['selected_job']);self.assertFalse(d['native_storage_preemption'])
    def test_real_hello_socket_counts(self):
        self.start_host();s,hello=self.connect();self.assertEqual(self.host.diagnostics()['activity']['read_connections'],1)
    def test_real_upload_socket_counts(self):
        self.start_host();s,hello=self.connect(True);self.assertEqual(self.host.diagnostics()['activity']['upload_connections'],1)
    def test_read_and_upload_connections_both_count(self):
        self.start_host();self.connect();self.connect(True);self.assertEqual(self.host.diagnostics()['activity']['connections'],2)
    def test_schedule_pauses_both_listeners(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.assertFalse(self.host.read.accepting);self.assertFalse(self.host.upload.accepting)
    def test_submission_is_not_automatic_dispatch(self):
        self.start_host();self.submit_close();self.tick(5);self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED');self.assertEqual(self.window.phase,'OPEN')
    def test_one_transition_per_tick(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick();self.assertEqual(self.host.jobs.poll(self.jid())['state'],'VALIDATED');self.tick();self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED')
    def test_direct_job_dispatch_when_accepting_refused(self):
        self.start_host();self.submit_close();self.host.jobs.step(self.jid());self.host.jobs.step(self.jid());self.err('ADMISSION_NOT_PAUSED',lambda:self.host.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_selector_orphan_detected_not_fake_zero(self):
        self.start_host();s,hello=self.connect();saved=dict(self.host.read.connections);self.host.read.connections.clear()
        try:self.err('ACTIVITY_MISMATCH',self.host.activity.snapshot)
        finally:self.host.read.connections.update(saved)
    def test_connection_without_selector_detected(self):
        self.start_host();s,hello=self.connect();c=next(iter(self.host.read.connections.values()));self.host.read.selector.unregister(c.socket)
        try:self.err('ACTIVITY_MISMATCH',self.host.activity.snapshot)
        finally:self.host.read.selector.register(c.socket,selectors.EVENT_READ,c)
    def test_extra_selector_registration_detected(self):
        self.start_host();a,b=socket.socketpair()
        try:
            self.host.read.selector.register(a,selectors.EVENT_READ,object());self.err('ACTIVITY_MISMATCH',self.host.activity.snapshot);self.host.read.selector.unregister(a)
        finally:a.close();b.close()
    def test_activity_port_uses_real_pins(self):
        self.ready_keeper();self.start_host();from par_keeper import make_call
        oid=sorted(self.bundle.objects)[0];call=make_call(self.p,self.cs,self.cap,'get',self.lid,h('pin'),oid)
        with self.keeper.reader(self.lid,oid,self.cap,call):self.assertEqual(self.host.activity.snapshot()['reader_pins'],1)
        self.assertEqual(self.host.activity.snapshot()['reader_pins'],0)
    def test_wrong_thread_has_no_mutation(self):
        self.start_host();out=[]
        def other():
            try:self.host.tick(0)
            except Exception as e:out.append(e.code)
        t=threading.Thread(target=other);t.start();t.join();self.assertEqual(out,['SCHEDULER_OWNER']);self.assertEqual(self.host.diagnostics()['mode'],'SERVING')
    def test_schedule_invalid_job_leaves_accepting(self):
        self.start_host();self.err(None,lambda:self.host.schedule(h('absent')));self.assertTrue(self.host.read.accepting)
    def test_schedule_rejects_second_selected_job(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.err('SCHEDULER_BUSY',lambda:self.host.schedule(self.jid('two')))
    def test_invalid_tick_deadline(self):
        self.start_host()
        for v in (True,-1,2,float('nan'),float('inf'),'0'):self.err('SCHEDULER_INPUT',lambda v=v:self.host.tick(v))
    def test_invalid_drain_timeout(self):
        for v in (True,0,-1,float('nan'),float('inf'),'5'):self.err('SCHEDULER_INPUT',lambda v=v:self.start_host(drain_timeout=v))
    def test_close_idempotent_releases_sockets(self):
        self.start_host();self.host.close();self.host.close();self.assertFalse(self.socket_path.exists());self.assertFalse(self.upload_path.exists())
