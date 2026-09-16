from unittest.mock import patch
from jobs_support import JobTest,h
from par_upload_window import contract as w
from par_keeper import make_call
from par_verified_host import VerificationProvider
class JobIntegration(JobTest):
    def test_real_keeper_read_pin_blocks_prepared_job(self):
        lid=self.reserve();self.fill(lid);self.seal(lid);oid=sorted(self.bundle.objects)[0];call=make_call(self.p,self.cs,self.cap,'get',lid,h('read-job-pin'),oid)
        self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid())
        with self.keeper.reader(lid,oid,self.cap,call) as reader:
            self.assertEqual(reader.read(),self.bundle.objects[oid]);self.assertEqual(self.jobs.step(self.jid())['waiting_reason'],'ACTIVE_TRANSFERS');self.assertEqual(self.window.phase,'OPEN')
        self.assertEqual(self.jobs.step(self.jid())['state'],'SUCCEEDED')
    def install_cache(self):
        self.jobs.close();self.cache=VerificationProvider(self.p,mode='signatures');self.keeper.provider=self.cache;self.window.provider=self.cache;self.window._inner.provider=self.cache
        self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:0)
        self.addCleanup(self.cache.close)
    def test_warm_cache_does_not_cache_authority(self):
        self.install_cache();self.jobs.submit(self.jid(),**self.close_args());self.prepare(self.jid());self.jobs.poll(self.jid());self.assertGreater(self.cache.statistics()['hits'],0)
        self.change_authority();self.err('STALE_AUTHORITY',lambda:self.jobs.step(self.jid()));self.assertEqual(self.window.phase,'OPEN')
    def test_warm_cache_rechecks_archive_bytes(self):
        self.install_cache();self.jobs.submit(self.jid(),**self.close_args());self.complete(self.jid());self.jobs.result(self.jid());p=next(self.window.archives.iterdir());raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]));self.err(None,lambda:self.jobs.result(self.jid()))
    def test_warm_cache_rechecks_job_bytes(self):
        self.install_cache();self.jobs.submit(self.jid(),**self.close_args());self.jobs.poll(self.jid());p=self.jobs.journal.path(self.jid());raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]));self.err(None,lambda:self.jobs.poll(self.jid()))
    def test_close_compact_open_new_upload_then_old_refused(self):
        self.jobs.submit(self.jid(),**self.close_args());old=self.beginwrapped;self.complete(self.jid())
        self.jobs.submit(self.jid('compact'),action='compact');self.complete(self.jid('compact'));receipt=self.jobs.result(self.jid('compact'));grant=self.grant_for(2,w.digest(receipt))
        self.jobs.submit(self.jid('open'),action='open',command=grant);self.complete(self.jid('open'));self.grant=grant
        self.err('WINDOW_SCOPE',lambda:self.window.execute(old));token=self.upload_stage(9);self.assertEqual(self.window.diagnostics()['records'],1)
    def test_keeper_objects_and_retention_not_mutated(self):
        lid=self.reserve();self.fill(lid);self.seal(lid);before=dict(self.keeper._lease(lid));objects={p.name:p.read_bytes() for p in self.keeper.object_path(lid,sorted(self.bundle.objects)[0]).parent.iterdir()}
        self.jobs.submit(self.jid(),**self.close_args());self.complete(self.jid());self.jobs.submit(self.jid('compact'),action='compact');self.complete(self.jid('compact'))
        self.assertEqual(dict(self.keeper._lease(lid)),before);self.assertEqual({p.name:p.read_bytes() for p in self.keeper.object_path(lid,sorted(self.bundle.objects)[0]).parent.iterdir()},objects)
    def test_two_jobs_prepared_on_same_target_second_blocked(self):
        a=self.close_args();other=w.approve_close(self.p,self.s.owner,self.keeper.authority,self.grant,a['archive'],h('other-close'))
        self.jobs.submit(self.jid(),**a);self.jobs.submit(self.jid('other'),action='close',command=other,archive=a['archive']);self.prepare(self.jid());self.prepare(self.jid('other'));self.jobs.step(self.jid());self.err('JOB_TARGET_CHANGED',lambda:self.jobs.step(self.jid('other')))
    def test_prepare_does_not_use_generic_admin_dispatch(self):
        self.jobs.submit(self.jid(),**self.close_args())
        with patch('par_window_host.host.administer',side_effect=AssertionError('generic dispatch')):self.complete(self.jid())
