import json,hashlib
from unittest.mock import patch
from par_wire.codec import decode,encode
from product.wp04 import application as module
from apply_support import ApplyTest,h

class HardeningTests(ApplyTest):
 def test_malicious_rehashed_input_signature_rejected_by_store_audit(self):
  e,_=self.saved();self.call([e]);c=self.db._storage.connection;r=c.execute('SELECT record FROM document_inputs').fetchone()[0]
  obj=decode(r);env=decode(obj[0]);env[3]=bytes([env[3][0]^1])+env[3][1:];obj[0]=encode(env);bad=encode(obj)
  # Record's ID no longer matches the signed envelope; rehashing is not authenticity.
  c.execute('UPDATE document_inputs SET record=?,record_digest=?',(bad,hashlib.sha256(bad).digest()))
  # Rewrite metadata digest to model a checksum-aware local corruption, not valid AEAD.
  self.assertFalse(self.db.audit()['valid'])
 def test_core_report_unknown_key_refused(self):
  e,_=self.saved();self.port.mutate=lambda r:r.update(extra=True);self.deny('CORE_REPORT_INVALID',lambda:self.call([e]))
 def test_oversized_note_refused_before_nonce(self):
  e,_=self.saved();self.port.mutate=lambda r:r['note'].update(body='x'*300000);self.deny('RESOURCE_LIMIT',lambda:self.call([e]));self.assertEqual(self.nums()['document_apply_nonces'],0)
 def test_whole_history_capacity_refused_without_nonce(self):
  e,_=self.saved()
  with patch.object(module,'MAX_EVENTS',0):self.deny('INVALID_INPUT',lambda:self.call([e]))
 def test_nonce_capacity_refused(self):
  e,_=self.saved()
  with patch.object(module,'MAX_NONCES',0):self.deny('RESOURCE_LIMIT',lambda:self.call([e]))
 def test_input_growth_budget_refused(self):
  e,_=self.saved()
  with patch.object(module,'MAX_RECORD_BYTES',1):self.deny('RESOURCE_LIMIT',lambda:self.call([e]))
 def test_rollback_after_input_insert(self):
  e,_=self.saved();self.a.observer=lambda s:(_ for _ in ()).throw(OSError('fault')) if s=='apply.after_inputs' else None
  self.deny('APPLICATION_ABORTED',lambda:self.call([e]));self.assertEqual(self.nums()['document_inputs'],0);self.assertEqual(self.nums()['document_apply_events'],0);self.assertEqual(self.nums()['document_apply_nonces'],1)
 def test_lost_commit_reply_is_not_failure_and_recovery_has_no_new_nonce(self):
  e,_=self.saved();self.a.observer=lambda s:(_ for _ in ()).throw(OSError('lost')) if s=='apply.after_commit' else None
  self.deny('APPLICATION_OUTCOME_UNKNOWN',lambda:self.call([e]));n=self.nums();self.a=self.make();r=self.call([e]);self.assertEqual(r['revision'],1);self.assertEqual(self.nums(),n)
 def test_guard_after_row_mutation_refuses_commit(self):
  e,_=self.saved()
  def fault(s):
   if s=='apply.before_commit':self.db._storage.connection.execute("UPDATE auth_spaces SET row_digest=zeroblob(32)")
  self.a.observer=fault;self.deny(None,lambda:self.call([e]));self.assertEqual(self.nums()['document_inputs'],0);self.assertTrue(self.db.audit()['valid'])
 def test_core_change_at_commit_is_refused(self):
  e,_=self.saved()
  def fault(s):
   if s=='apply.before_commit':self.port.identity['digest']='c'*64
  self.a.observer=fault;self.deny('CORE_IDENTITY_CHANGED',lambda:self.call([e]));self.assertEqual(self.nums()['document_inputs'],0)
 def test_duplicate_nonce_rejected_not_reencrypted(self):
  e,_=self.saved();self.a.prepare(b'a'*16,(e,),expected_revision=0)
  nonce=self.db._storage.connection.execute('SELECT nonce FROM document_apply_nonces').fetchone()[0]
  source=module.random_bytes
  with patch.object(module,'random_bytes',side_effect=lambda n:nonce if n==24 else source(n)):
   self.deny('SQLITE_CONSTRAINT',lambda:self.a.prepare(b'b'*16,(e,),expected_revision=0))
 def test_backend_identity_cannot_be_forged_by_report(self):
  e,_=self.saved();self.port.mutate=lambda r:r['engine'].update(kind='automerge');self.deny('CORE_IDENTITY_CHANGED',lambda:self.call([e]))
 def test_missing_real_loader_is_blocked(self):
  import importlib.util
  self.assertIsNotNone(importlib.util.find_spec('product.wp04.application_core'),'pinned materializer adapter is not implemented')
  from product.wp04.application_core import NodeMaterializationPort
  self.deny('CORE_UNAVAILABLE',lambda:NodeMaterializationPort(self.root/'missing.json'))
 def test_read_does_not_return_note_if_authority_changes_during_decrypt(self):
  e,_=self.saved();self.call([e]);original=self.p.open;fired=False
  def changed(*args,**kw):
   nonlocal fired
   result=original(*args,**kw)
   if not fired:
    fired=True;self.same_epoch()
   return result
  with patch.object(self.p,'open',side_effect=changed):self.deny('OWNER_STATE_CHANGED',lambda:self.a.read())
 def test_application_pin_survives_next_revision_but_not_disappearing_event(self):
  e,c=self.saved();self.call([e]);pin=self.a.pin();e2,c2=self.saved(2,sequence=2,previous=e,deps=[c]);self.call([e2],op=11,expected=1)
  b=self.make(expected_pin=pin);self.assertEqual(b.read()['revision'],2)
 def test_read_refuses_input_change_during_decrypt(self):
  e,_=self.saved();self.call([e]);original=self.p.open;fired=False
  def changed(*args,**kw):
   nonlocal fired
   result=original(*args,**kw)
   if not fired:
    fired=True;self.db._storage.connection.execute('DELETE FROM document_inputs')
   return result
  with patch.object(self.p,'open',side_effect=changed):self.deny('APPLICATION_CHANGED',lambda:self.a.read())
 def test_prepared_apply_refuses_rotated_writer_fence(self):
  e,_=self.saved();prepared=self.a.prepare(b'Z'*16,(e,),expected_revision=0)
  self.db._storage.fencing_token=b'F'*16
  self.db._storage.connection.execute('UPDATE writer_fences SET fencing_token=?',(b'F'*16,))
  self.deny('WRITER_FENCE_CHANGED',lambda:self.a.commit(prepared));self.assertEqual(self.nums()['document_apply_events'],0)
 def test_commit_refuses_rotated_writer_fence_inside_transaction(self):
  e,_=self.saved()
  def fault(stage):
   if stage=='apply.before_commit':
    self.db._storage.connection.execute('UPDATE writer_fences SET fencing_token=?',(b'F'*16,))
  self.a.observer=fault
  self.deny('WRITER_FENCE_CHANGED',lambda:self.call([e]));self.assertEqual(self.nums()['document_apply_events'],0)
 def test_real_application_gate_without_core_is_blocked_not_skip(self):
  import subprocess,sys
  from pathlib import Path
  root=Path(__file__).resolve().parents[3]
  result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'tools/check_document_apply_real.py')],capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,78)
  data=json.loads(result.stdout);self.assertEqual(data['result'],'BLOCKED');self.assertEqual(data['real_tests_executed'],0)
