"""Real SQLite/crypto checks for the read-only owner adapter; synthetic keys only."""
import importlib, json, threading
from pathlib import Path
from auth_store_support import AuthStoreTest,h

class StoreObservationTest(AuthStoreTest):
 def setUp(self):
  super().setUp()
  try:self.mod=importlib.import_module('product.runtime_read.observer')
  except ModuleNotFoundError:self.mod=None
  self.assertIsNotNone(self.mod,'Store observation adapter not implemented')
  self.start();self.obs=self.make()
 def make(self,**kw):
  return self.mod.StoreObserver(self.db,app_id=self.s.app,space_id=self.s.space,document_id=kw.get('document',h('doc')),device_id=kw.get('device',self.s.devices[0]['id']),local_secret=kw.get('secret',h('local-secret')))
 def test_absent_not_failure(self):
  r=self.obs.observe(bytes(16));self.assertEqual(r['operation']['state'],'NOT_OBSERVED');self.assertFalse(r['document']['applied']);self.assertFalse(r['capabilities']['sharedCommit'])
 def test_real_committed_receipt_without_original_plaintext(self):
  req=self.request();receipt=self.writer().write(*req);r=self.obs.observe(req[0])
  self.assertEqual(r['operation']['state'],'OBSERVED_COMMITTED');self.assertEqual(r['operation']['commitId'],receipt.envelope_id.hex());self.assertTrue(r['operation']['receiptVerified']);self.assertEqual(r['document']['pendingCount'],1)
  text=json.dumps(r);self.assertNotIn(req[2].decode(),text);self.assertNotIn(req[3].decode(),text);self.assertNotIn(h('local-secret').hex(),text)
 def test_nonce_only_not_commit(self):
  req=self.request();self.writer().prepare(*req);r=self.obs.observe(req[0]);self.assertEqual(r['operation']['state'],'NOT_OBSERVED')
 def test_read_has_no_writes_or_signatures(self):
  req=self.request();self.writer().write(*req);c=self.db._storage.connection;before=c.total_changes;dump=list(c.iterdump());original=self.p.sign
  self.p.sign=lambda *args:(_ for _ in ()).throw(AssertionError('read attempted signing'))
  try:
   for i in range(3):self.obs.observe(req[0])
  finally:self.p.sign=original
  self.assertEqual(c.total_changes,before);self.assertEqual(list(c.iterdump()),dump)
 def test_other_document_operation_hidden(self):
  req=self.request();self.writer().write(*req);r=self.make(document=h('other')).observe(req[0]);self.assertEqual(r['operation']['state'],'NOT_OBSERVED');self.assertEqual(r['document']['envelopeCount'],0)
 def test_other_device_operation_hidden(self):
  req=self.request();self.writer().write(*req);r=self.make(device=self.s.devices[1]['id']).observe(req[0]);self.assertEqual(r['operation']['state'],'NOT_OBSERVED')
 def test_wrong_secret_rejects(self):
  req=self.request();self.writer().write(*req)
  with self.assertRaises(self.mod.ObservationError):self.make(secret=h('wrong')).observe(req[0])
 def test_corrupt_receipt_rejects(self):
  req=self.request();self.writer().write(*req);self.db._storage.connection.execute("UPDATE commit_ledger SET receipt_encrypted=?",(b'bad',))
  with self.assertRaises(self.mod.ObservationError):self.obs.observe(req[0])
 def test_corrupt_cache_rejects(self):
  req=self.request();self.writer().write(*req);self.db._storage.connection.execute("UPDATE local_commit_meta SET encrypted_cache=?",(b'bad',))
  with self.assertRaises(self.mod.ObservationError):self.obs.observe(req[0])
 def test_corrupt_signed_payload_rejects(self):
  req=self.request();self.writer().write(*req);self.db._storage.connection.execute("UPDATE envelopes SET encrypted_bytes=?",(b'bad',))
  with self.assertRaises(self.mod.ObservationError):self.obs.observe(req[0])
 def test_result_after_authority_update(self):
  req=self.request();self.writer().write(*req);self.same_epoch();r=self.obs.observe(req[0]);self.assertEqual(r['operation']['state'],'OBSERVED_COMMITTED');self.assertFalse(r['capabilities']['sharedCommit'])
 def test_restored_reopened_does_not_activate(self):
  req=self.request();self.writer().write(*req);self.reopen();self.obs=self.make();before=self.db.status(self.s.space);r=self.obs.observe(req[0]);self.assertEqual(self.db.status(self.s.space),before);self.assertFalse(r['authority']['writeAuthorized']);self.assertEqual(r['operation']['state'],'OBSERVED_COMMITTED')
 def test_uncertain_authority_disallows_projection_of_ready(self):
  self.db._failed[self.s.space]=h('missing');r=self.obs.observe();self.assertEqual(r['authority']['state'],'AUTH_PERSISTENCE_UNCERTAIN');self.assertFalse(r['authority']['writeAuthorized'])
 def test_returned_objects_not_shared(self):
  r=self.obs.observe();r['capabilities']['sharedCommit']=True;self.assertFalse(self.obs.observe()['capabilities']['sharedCommit'])
 def test_sequence_increases(self):
  a=self.obs.observe();b=self.obs.observe();self.assertEqual(int(b['sequence']),int(a['sequence'])+1);self.assertNotEqual(a['revision'],b['revision'])
 def test_close_blocks(self):
  self.obs.close()
  with self.assertRaises(self.mod.ObservationError):self.obs.observe()
 def test_wrong_thread_refused(self):
  errors=[]
  def call():
   try:self.obs.observe()
   except self.mod.ObservationError as e:errors.append(e.code)
  t=threading.Thread(target=call);t.start();t.join();self.assertEqual(errors,['WRONG_OWNER']);self.obs.observe()
 def test_scope_not_enrolled(self):
  with self.assertRaises(self.mod.ObservationError):
   self.mod.StoreObserver(self.db,app_id='wrong.app',space_id=self.s.space,document_id=h('doc'),device_id=self.s.devices[0]['id'],local_secret=h('local-secret')).observe()
 def test_pending_outbox_never_retention_receipt(self):
  req=self.request();self.writer().write(*req);r=self.obs.observe(req[0]);self.assertEqual(r['operation']['outboxState'],'pending');self.assertFalse(r['replicationObserved'])
 def test_no_operation_query_explicit(self):
  r=self.obs.observe();self.assertEqual(r['operation']['state'],'NOT_QUERIED');self.assertIsNone(r['operation']['id'])
 def test_invalid_operation_id(self):
  for v in [True,1,'00',b'bad',bytearray(16)]:
   with self.assertRaises(self.mod.ObservationError):self.obs.observe(v)
 def test_no_plaintext_even_applied_flag_forged(self):
  req=self.request();self.writer().write(*req);self.db._storage.connection.execute("UPDATE envelopes SET state='applied'")
  with self.assertRaises(self.mod.ObservationError):self.obs.observe(req[0])

 def test_committed_reply_loss_can_be_inspected_without_replay(self):
  req=self.request()
  def fail(stage):
   if stage=='commit.after_commit':raise OSError('lost reply')
  self.db.observer=fail
  with self.assertRaises(Exception):self.writer().write(*req)
  self.db.observer=None;before=self.count('issued_nonces');r=self.obs.observe(req[0]);self.assertEqual(r['operation']['state'],'OBSERVED_COMMITTED');self.assertEqual(self.count('issued_nonces'),before)
 def test_epoch_change_keeps_local_result_but_no_write(self):
  req=self.request();self.writer().write(*req);self.next_epoch();r=self.obs.observe(req[0]);self.assertEqual(r['operation']['state'],'OBSERVED_COMMITTED');self.assertEqual(r['operation']['outboxState'],'rebase-required');self.assertFalse(r['authority']['writeAuthorized'])
 def test_wrong_process_refused(self):
  import os
  rd,wr=os.pipe();pid=os.fork()
  if pid==0:
   os.close(rd)
   try:self.obs.observe();result=b'BAD'
   except self.mod.ObservationError as e:result=e.code.encode()
   os.write(wr,result);os._exit(0)
  os.close(wr);out=os.read(rd,200);os.close(rd);os.waitpid(pid,0);self.assertEqual(out,b'WRONG_OWNER');self.obs.observe()
 def test_new_reader_has_new_stream(self):
  a=self.obs.observe();b=self.make().observe();self.assertNotEqual(a['streamId'],b['streamId']);self.assertEqual(a['storeGeneration'],b['storeGeneration'])
 def test_observation_changes_detected_after_audit(self):
  original=self.db.audit
  def audit():
   result=original();self.db._storage.connection.execute('UPDATE writer_fences SET owner_process=?',(bytes(16),));return result
  self.db.audit=audit
  with self.assertRaises(self.mod.ObservationError) as e:self.obs.observe()
  self.assertEqual(e.exception.code,'OBSERVATION_CHANGED')
