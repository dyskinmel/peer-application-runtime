import hashlib,json,os,unittest
from fetch_support import LocalFixture,h,Peer

class ResumeTests(LocalFixture,unittest.TestCase):
    def test_plan_save_load(self):
        p=self.make_plan();path=self.root/'plan.cbor';sha=p.save(path)
        self.assertEqual(sha,p.digest);self.assertEqual(os.stat(path).st_mode&0o777,0o600)
        self.assertEqual(self.m.FetchPlan.load(path,expected_sha256=sha),p)
    def test_no_plan_overwrite(self):
        p=self.make_plan();path=self.root/'plan';p.save(path)
        with self.assertRaises(self.m.FetchError):p.save(path)
        self.assertEqual(path.read_bytes(),p.to_bytes())
    def test_pinned_load_tamper(self):
        p=self.make_plan();path=self.root/'plan';p.save(path);path.write_bytes(b'bad')
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.load(path,expected_sha256=p.digest)
    def test_symlink_rejected(self):
        p=self.make_plan();real=self.root/'real';p.save(real);link=self.root/'link';link.symlink_to(real)
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.load(link,expected_sha256=p.digest)
    def test_hardlink_rejected(self):
        p=self.make_plan();real=self.root/'real';p.save(real);os.link(real,self.root/'link')
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.load(real,expected_sha256=p.digest)
    def test_unprivate_directory_rejected(self):
        parent=self.root/'public';parent.mkdir(mode=0o755)
        with self.assertRaises(self.m.FetchError):self.make_plan().save(parent/'plan')
    def test_unprivate_file_rejected(self):
        p=self.make_plan();path=self.root/'plan';p.save(path);path.chmod(0o644)
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.load(path,expected_sha256=p.digest)
    def test_reconcile_empty_does_not_contact_remote(self):
        c=self.client();v=c.reconcile();self.assertEqual(v['stored'],0);self.assertEqual(v['state'],'PARTIAL_PENDING');self.assertTrue(all(x['state']=='NOT_OBSERVED'for x in v['items']))
    def test_reconcile_resyncs_existing_and_keeps_unapplied(self):
        for row in self.remote.chain():self.local.box.receive(*row)
        c=self.client();v=c.reconcile();self.assertEqual(v['stored'],2);self.assertEqual(v['state'],'COMPLETE_PENDING')
        self.assertFalse(v['applied']or v['localCommitted']or v['replicated']or v['acknowledged']);self.assertEqual(self.local.db._storage.connection.execute('SELECT COUNT(*) FROM commit_ledger').fetchone()[0],0)
    def test_dependency_waiting_then_ready(self):
        a,b=self.remote.chain();self.local.box.receive(*b);v=self.client().reconcile();rows=[r for r in v['items']if r['state']=='INBOX_STORED'];self.assertEqual(rows[0]['candidateState'],'WAITING_DEPENDENCIES')
        self.local.box.receive(*a);v=self.client().reconcile();self.assertTrue(all(r['candidateState']=='READY_FOR_CORE'for r in v['items']))
    def test_checkpoint_roundtrip(self):
        c=self.client();self.local.box.receive(*self.remote.chain()[0]);v=c.reconcile();path=self.root/'cp.json';sha=c.save_checkpoint(path)
        c2=self.client(c.plan);r=c2.restore_checkpoint(path,expected_sha256=sha);self.assertEqual(r['stored'],1)
    def test_checkpoint_detects_known_missing_record_after_reopen(self):
        c=self.client();self.local.box.receive(*self.remote.chain()[0]);path=self.root/'cp.json';sha=c.save_checkpoint(path);plan=c.plan
        self.local.close();next((self.root/'local/inbox/records').iterdir()).unlink();self.local=Peer(self.root/'local')
        with self.assertRaises(self.m.FetchError):self.client(plan).restore_checkpoint(path,expected_sha256=sha)
    def test_old_checkpoint_accepts_newly_stored_record(self):
        c=self.client();path=self.root/'cp.json';sha=c.save_checkpoint(path);self.local.box.receive(*self.remote.chain()[0]);self.assertEqual(c.restore_checkpoint(path,expected_sha256=sha)['stored'],1)
    def test_checkpoint_plan_mismatch(self):
        c=self.client();path=self.root/'cp';sha=c.save_checkpoint(path)
        c2=self.client(self.make_plan(descriptors=[]))
        with self.assertRaises(self.m.FetchError):c2.restore_checkpoint(path,expected_sha256=sha)
    def test_checkpoint_hash_mismatch(self):
        c=self.client();path=self.root/'cp';c.save_checkpoint(path)
        with self.assertRaises(self.m.FetchError):c.restore_checkpoint(path,expected_sha256='0'*64)
    def test_generation_change_requires_new_plan(self):
        c=self.client();self.gen[0]=10
        with self.assertRaises(self.m.FetchError):c.reconcile()
    def test_wrong_inbox_generation(self):
        with self.assertRaises(self.m.FetchError):self.client(self.make_plan(inbox_generation='0'*32))
    def test_progress_is_owned_copy(self):
        c=self.client();v=c.progress();v['items'].clear();self.assertEqual(len(c.progress()['items']),2)
    def test_quarantine_is_not_success(self):
        a=self.remote.chain()[0];self.local.box.receive(*a);self.local.box.receive(*self.remote.change('conflict'))
        self.assertEqual(self.client().reconcile()['state'],'REVIEW_REQUIRED')
    def test_descriptor_length_mismatch_on_reconcile(self):
        self.local.box.receive(*self.remote.chain()[0]);ds=[list(d)for d in self.descriptors];ds[0][2]+=1;ds[1][2]+=1
        with self.assertRaises(self.m.FetchError):self.client(self.make_plan(descriptors=ds)).reconcile()
