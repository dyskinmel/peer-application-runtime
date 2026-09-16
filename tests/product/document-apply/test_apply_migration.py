import sqlite3
from par_blob_store import BlobStore
from apply_support import ApplyTest,h

class MigrationTests(ApplyTest):
 def test_old_blob_store_refuses_schema4(self):
  self.close();self.deny('SCHEMA_MISMATCH',lambda:BlobStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
 def test_migration_explicit_preserves_pending_commits(self):
  # Create a separate v3 host with genuine authorization and payload records.
  root=self.root.parent/'old';old=self.db;original=self.root
  self.db=BlobStore.create(root,provider=self.p,allow_unpatched_sqlite=True);self.root=root
  try:
   self.db.enroll(self.s.app,self.s.space,self.s.genesis);self.db.observe(self.s.space,self.b['raw']);self.db.provide_membership(self.s.space,self.b['pages']);self.activate()
   e,_=self.saved();self.db.close()
   self.deny('SCHEMA_MISMATCH',lambda:self.Store.open(root,provider=self.p,allow_unpatched_sqlite=True))
   self.db=self.Store.migrate_v3(root,provider=self.p,allow_unpatched_sqlite=True)
   self.assertEqual(self.nums()['document_apply_events'],0);self.assertEqual(self.db._storage.connection.execute('SELECT state FROM envelopes').fetchone()[0],'pending')
   self.db.reactivate(self.s.space,self.s.devices[0]['secret']);self.a=self.make();self.assertFalse(self.call([e])['applied'])
  finally:
   self.db.close();self.db=old;self.root=original
 def test_migration_failure_keeps_v3(self):
  root=self.root.parent/'old';db=BlobStore.create(root,provider=self.p,allow_unpatched_sqlite=True);db.close()
  def fault(stage):
   if stage=='apply_migration.after_schema':raise OSError('stop before commit')
  with self.assertRaises(OSError):self.Store.migrate_v3(root,provider=self.p,allow_unpatched_sqlite=True,observer=fault)
  db=BlobStore.open(root,provider=self.p,allow_unpatched_sqlite=True)
  try:self.assertTrue(db.audit()['valid'])
  finally:db.close()
 def test_snapshot_preserves_encrypted_application_and_is_read_only(self):
  e,_=self.saved();self.call([e]);snap=self.root.parent/'snapshot';restored=self.root.parent/'restored'
  self.db._storage.export_snapshot(snap);self.Store.restore_snapshot(snap,restored,provider=self.p,allow_unpatched_sqlite=True)
  restored_db=self.Store.open(restored,provider=self.p,allow_unpatched_sqlite=True)
  try:
   self.assertTrue(restored_db._storage.restore_read_only);self.assertTrue(restored_db.audit()['valid'])
   self.assertEqual(restored_db._storage.connection.execute('SELECT count(*) FROM document_apply_events').fetchone()[0],1)
   a=self.Applier(restored_db,self.port,self.s.devices[0]['cert'],h('local-apply-secret'),app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'),allow_contract_double=True)
   self.deny('RESTORE_READ_ONLY',lambda:a.prepare(b'n'*16,(e,),expected_revision=1))
  finally:restored_db.close()
