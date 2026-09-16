"""Real pinned crypto, SQLite and replay gateway with public synthetic fixtures."""
import importlib
from pathlib import Path
from window_support import WindowTest,h
class JobTest(WindowTest):
    def setUp(self):
        super().setUp();self.jobs=None
        try:self.m=importlib.import_module('par_management_jobs')
        except ModuleNotFoundError:self.m=None
        self.assertTrue(self.m is not None and hasattr(self.m,'ManagementJobs'),'ManagementJobs candidate not implemented')
        self.jroot=Path(self.tmp.name)/'jobs';self.activity_count=0
        self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:self.activity_count)
    def tearDown(self):
        if getattr(self,'jobs',None) is not None:self.jobs.close();self.jobs=None
        super().tearDown()
    def jid(self,label='one'):return h('job-'+label)
    def retired_command(self):
        self.upload_stage(8);return self.wrap(self.retirement_request(),'retire')
    def close_args(self):
        self.terminal();a,c=self.proposed();return dict(action='close',command=c,archive=a)
    def prepare(self,j):
        self.assertEqual(self.jobs.step(j)['state'],'VALIDATED')
        self.assertEqual(self.jobs.step(j)['state'],'PREPARED')
    def complete(self,j):
        self.prepare(j);r=self.jobs.step(j);self.assertEqual(r['state'],'SUCCEEDED');return r
    def reopen_jobs(self,**kw):
        self.jobs.close();self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:self.activity_count,**kw);return self.jobs
    def reopen_all(self):
        self.jobs.close();self.jobs=None;self.window.close();self.keeper.close()
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id)
        return self.reopen_jobs_new()
    def reopen_jobs_new(self):
        self.jobs=self.m.ManagementJobs(self.window,self.jroot,activity=lambda:self.activity_count);return self.jobs
