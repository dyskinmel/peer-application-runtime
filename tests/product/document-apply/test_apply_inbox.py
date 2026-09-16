import hashlib,shutil
from par_crypto import objects
from par_wire.codec import decode
from product.wp04.inbox import SyncInbox
from apply_support import ApplyTest,h

class InboxTests(ApplyTest):
 def box(self):
  b=SyncInbox.create(self.root.parent/'inbox',self.db,app_id=self.s.app,space_id=self.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'))
  self.addCleanup(b.close);self.a=self.make(inbox=b);return b
 def remote(self,label,seq=1,previous=None,deps=(),index=0):
  _,head,p,_=self.request(sequence=seq,previous=previous,index=index);head[12]=h(label);head[10]=list(deps)
  raw=objects.seal_change(self.p,self.s.secret,self.s.devices[index]['seed'],head,p,h('nonce'+label)[:24])
  return raw,self.s.devices[index]['cert']
 def test_inbox_inputs_copied_atomically_not_committed_as_local_operations(self):
  b=self.box();raw,cert=self.remote('a');b.receive(raw,cert);eid=objects.envelope_id(raw);r=self.call([eid]);self.assertFalse(r['applied']);self.assertEqual(self.count('envelopes'),0);self.assertEqual(self.nums()['document_inputs'],1)
 def test_reverse_dependency_arrival(self):
  b=self.box();a,cert=self.remote('a');ea=objects.envelope_id(a);v,cv=self.remote('b',seq=2,previous=ea,deps=[h('a')]);b.receive(v,cv);ev=objects.envelope_id(v)
  self.deny('DEPENDENCIES_MISSING',lambda:self.call([ev]));b.receive(a,cert);self.assertEqual(self.call([ev])['heads'],[h('b').hex()])
 def test_materialization_read_does_not_need_inbox_after_copy(self):
  b=self.box();raw,cert=self.remote('a');b.receive(raw,cert);self.call([objects.envelope_id(raw)]);b.close();shutil.rmtree(b.root)
  self.assertEqual(self.a.read()['revision'],1)
 def test_store_plus_inbox_dependency_union(self):
  b=self.box();ea,ca=self.saved();raw,cert=self.remote('b',seq=2,previous=ea,deps=[ca]);b.receive(raw,cert)
  self.assertEqual(self.call([objects.envelope_id(raw)])['heads'],[h('b').hex()]);self.assertEqual(self.nums()['document_inputs'],2)
 def test_seen_valid_equivocation_prevents_apply(self):
  b=self.box();a,c=self.remote('a');other,oc=self.remote('other');b.receive(a,c);b.receive(other,oc)
  self.deny('ACTOR_EQUIVOCATION',lambda:self.call([objects.envelope_id(a)]))
 def test_input_mutation_after_prepare_is_rejected(self):
  b=self.box();a,c=self.remote('a');b.receive(a,c);eid=objects.envelope_id(a);p=self.a.prepare(b'p'*16,(eid,),expected_revision=0)
  path=b.root/'records'/(eid.hex()+'.cbor');data=path.read_bytes();path.write_bytes(data[:-1]+bytes([data[-1]^1]))
  self.deny('INPUTS_CHANGED',lambda:self.a.commit(p));self.assertEqual(self.nums()['document_apply_events'],0)
 def test_nonce_is_consumed_even_when_commit_is_cancelled(self):
  b=self.box();a,c=self.remote('a');b.receive(a,c);eid=objects.envelope_id(a);self.a.prepare(b'p'*16,(eid,),expected_revision=0)
  self.a.prepare(b'q'*16,(eid,),expected_revision=0);rows=list(self.db._storage.connection.execute('SELECT nonce,used_by FROM document_apply_nonces'))
  self.assertEqual(len(rows),2);self.assertNotEqual(rows[0][0],rows[1][0]);self.assertTrue(all(r[1] is None for r in rows))
