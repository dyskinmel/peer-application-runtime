import os,stat
from submit_support import SubmitTest,h
class SubmitStaging(SubmitTest):
    def test_begin_no_job(self):
        d=self.descriptor();v=self.st.begin(d);self.assertEqual(v['state'],'RECEIVING');self.assertEqual(self.host.jobs.list(),[]);self.assertIsNone(self.host.selected)
    def test_duplicate_begin(self):
        d=self.descriptor();self.st.begin(d);before=self.st.diagnostics();self.st.begin(d);self.assertEqual(self.st.diagnostics(),before)
    def test_conflicting_descriptor(self):
        self.st.begin(self.descriptor());self.err('SUBMIT_CONFLICT',lambda:self.st.begin(self.descriptor(payload_hash=h('changed'))))
    def test_ready_prefix(self):
        d,r=self.ready();v=self.st.progress(d);self.assertEqual(v['received'],len(r));self.assertEqual(v['prefix_hash'],self.sc.sha(r).hex());self.assertEqual(v['state'],'READY')
    def test_exact_chunk_retry(self):
        r=self.payload();d=self.descriptor(r);self.st.begin(d);self.st.chunk(d,0,r[:8]);before=self.st.progress(d);self.st.chunk(d,0,r[:8]);self.assertEqual(self.st.progress(d),before)
    def test_gap(self):
        d=self.descriptor();self.st.begin(d);self.err('SUBMIT_OFFSET',lambda:self.st.chunk(d,1,b'a'))
    def test_overlap(self):
        d=self.descriptor();self.st.begin(d);self.st.chunk(d,0,b'abcdefgh');self.err('SUBMIT_OFFSET',lambda:self.st.chunk(d,4,b'efghzzzz'))
    def test_wrong_repeated_chunk(self):
        d=self.descriptor();self.st.begin(d);self.st.chunk(d,0,b'abcdefgh');self.err('SUBMIT_CONFLICT',lambda:self.st.chunk(d,0,b'ABCDEFGH'))
    def test_empty_chunk(self):
        d=self.descriptor();self.st.begin(d);self.err(None,lambda:self.st.chunk(d,0,b''))
    def test_chunk_limit(self):
        d=self.descriptor();self.st.begin(d);self.err(None,lambda:self.st.chunk(d,0,b'a'*(self.sc.CHUNK+1)))
    def test_bool_offset(self):
        d=self.descriptor();self.st.begin(d);self.err(None,lambda:self.st.chunk(d,False,b'a'))
    def test_wrong_final_hash(self):
        r=self.payload();d=self.descriptor(r,payload_hash=h('bad'));self.st.begin(d);self.err('SUBMIT_HASH',lambda:self.st.chunk(d,0,r));self.assertEqual(self.st.progress(d)['received'],0)
    def test_restart_partial(self):
        r=self.payload();d=self.descriptor(r);self.st.begin(d);self.st.chunk(d,0,r[:10]);self.reopen();self.st.chunk(d,10,r[10:]);self.assertEqual(self.st.progress(d)['state'],'READY')
    def test_acknowledged_corruption_rejected(self):
        d,r=self.ready();p=self.st.payload_path(self.jid());data=bytearray(p.read_bytes());data[0]^=1;p.write_bytes(data);self.err('SUBMIT_HASH',lambda:self.st.progress(d))
    def test_missing_acknowledged_payload(self):
        d,r=self.ready();self.st.payload_path(self.jid()).unlink();self.err(None,lambda:self.st.progress(d))
    def test_unack_tail_trimmed_by_explicit_chunk(self):
        r=self.payload();d=self.descriptor(r);self.st.begin(d);self.st.chunk(d,0,r[:8]);p=self.st.payload_path(self.jid());p.write_bytes(r[:8]+b'unacked');self.reopen();self.st.chunk(d,8,r[8:]);self.assertEqual(p.read_bytes(),r)
    def test_symlink_payload_refused(self):
        d,r=self.ready();p=self.st.payload_path(self.jid());other=p.with_suffix('.other');p.rename(other);p.symlink_to(other);self.err(None,lambda:self.st.progress(d))
    def test_private_mode(self):
        d,r=self.ready();p=self.st.payload_path(self.jid());self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600);p.chmod(0o644);self.err(None,lambda:self.st.progress(d))
    def test_capacity_no_record_created(self):
        # Finite byte budget tested on a fresh private root.
        self.st.close();self.sroot=self.sroot.with_name('small');self.st=self.sm.Submissions(self.ctl,self.sroot,max_bytes=1024)
        d=self.descriptor(size=1025);self.err('SUBMIT_CAPACITY',lambda:self.st.begin(d));self.assertEqual(self.st.diagnostics()['records'],0)
    def test_record_limit_duplicate_allowed(self):
        self.st.close();self.sroot=self.sroot.with_name('one');self.st=self.sm.Submissions(self.ctl,self.sroot,max_records=1)
        d=self.descriptor();self.st.begin(d);self.st.begin(d);self.err('SUBMIT_CAPACITY',lambda:self.st.begin(self.descriptor(jid=h('two'))))
    def test_controller_revision_change_rejects_pending(self):
        d,r=self.ready();self.ctl.replace_controller(self.op,2);self.err('STALE_CONTROLLER',lambda:self.st.submit(d));self.assertEqual(self.host.jobs.list(),[])
    def test_wrong_store_rejected_before_allocation(self):
        d=self.descriptor(store=h('wrong'));self.err(None,lambda:self.st.begin(d));self.assertEqual(self.st.diagnostics()['records'],0)
