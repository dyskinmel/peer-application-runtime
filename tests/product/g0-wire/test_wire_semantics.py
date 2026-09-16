import copy
from wire_support import WireCase, sample, ID, OTHER

class NegotiationTests(WireCase):
 def pair(self):
  f=self.mod('framing');a=sample(1);b=sample(1);b[2]=b'r'*16;b[4][2]=b'b'*32;b[4][6]=b'peer-b'
  return f.encode_frame(a),f.encode_frame(b)
 def build(self,a=None,b=None,**kw):
  if a is None:a,b=self.pair()
  return self.mod('negotiation').build_transcript(a,b,expected_profile=OTHER,expected_initiator_peer=b'peer-a',expected_responder_peer=b'peer-b',**kw)
 def test_shared_id_deterministic_not_authentication(self):
  a=self.build();b=self.build();self.assertEqual(a.candidate_session_id,b.candidate_session_id);self.assertEqual(len(a.candidate_session_id),32);self.assertFalse(a.authenticated)
 def test_role_signatures_differ(self):
  t=self.build();self.assertNotEqual(t.signing_bytes('initiator'),t.signing_bytes('responder'))
 def test_all_hello_bytes_bound(self):
  f=self.mod('framing');a,b=self.pair();t=self.build(a,b);v=f.decode_frame(b);v[4][1]+=b'changed';self.assertNotEqual(t.candidate_session_id,self.build(a,f.encode_frame(v)).candidate_session_id)
 def test_request_ids_bound(self):
  f=self.mod('framing');a,b=self.pair();t=self.build(a,b);v=f.decode_frame(a);v[2]=b'x'*16;self.assertNotEqual(t.candidate_session_id,self.build(f.encode_frame(v),b).candidate_session_id)
 def test_nonce_mutation_changes_transcript(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][2]=b'z'*32;self.assertNotEqual(self.build(a,b).candidate_session_id,self.build(a,f.encode_frame(v)).candidate_session_id)
 def test_profile_mismatch(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][5]=ID;self.reject('PROFILE',self.build,a,f.encode_frame(v))
 def test_app_mismatch(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][0]='org.other.app';self.reject('APP_BINDING',self.build,a,f.encode_frame(v))
 def test_reflected_nonce(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][2]=ID;self.reject('REFLECTION',self.build,a,f.encode_frame(v))
 def test_transport_substitution(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][6]=b'peer-z';self.reject('TRANSPORT_BINDING',self.build,a,f.encode_frame(v))
 def test_no_silent_suite_downgrade(self):self.reject('NEGOTIATION',self.build,selected_suite=2)
 def test_no_silent_wire_downgrade(self):self.reject('NEGOTIATION',self.build,selected_wire='par/0')
 def test_missing_suite(self):
  f=self.mod('framing');a,b=self.pair();v=f.decode_frame(b);v[4][4]=[9];self.reject('NEGOTIATION',self.build,a,f.encode_frame(v))
 def test_unknown_signing_role(self):self.reject('ROLE',self.build().signing_bytes,'admin')
 def test_nonhello_frame(self):
  a,b=self.pair();self.reject('MESSAGE_TYPE',self.build,a,self.mod('framing').encode_frame(sample(2)))
 def test_replay_window_and_capacity(self):
  m=self.mod('negotiation');w=m.ReplayWindow(capacity=1,ttl=10);w.remember(b'a'*32,now=0);self.reject('REPLAY',w.remember,b'a'*32,now=1);self.reject('RESOURCE_LIMIT',w.remember,b'b'*32,now=1);w.remember(b'b'*32,now=10)
 def test_replay_clock_rollback(self):
  w=self.mod('negotiation').ReplayWindow();w.remember(b'a'*32,now=2);self.reject('CLOCK',w.remember,b'b'*32,now=1)

class PagingTests(WireCase):
 def pages(self):
  a=sample(20);a[4][1]=OTHER;a[4][3]=False;b=sample(20);b[4][2][0][0]=OTHER
  return a,b
 def walk(self,**kw):return self.mod('paging').InventoryWalk(space=ID,token=ID,**kw)
 def test_partial_is_not_complete(self):
  w=self.walk();a,b=self.pages();w.append(a,requested_cursor=None);self.assertEqual(w.snapshot()['coverage'],'INCOMPLETE');w.append(b,requested_cursor=OTHER);s=w.snapshot();self.assertEqual(s['coverage'],'PEER_SNAPSHOT_COMPLETE');self.assertEqual(len(s['items']),2)
 def test_token_change_invalidates_coverage(self):
  w=self.walk();a,b=self.pages();w.append(a,requested_cursor=None);b[4][0]=OTHER;self.reject('SNAPSHOT_CHANGED',w.append,b,requested_cursor=OTHER);self.assertEqual(w.snapshot()['coverage'],'INVALIDATED');self.assertEqual(w.snapshot()['items'],[])
 def test_wrong_space_rejected(self):
  w=self.walk();a,b=self.pages();a[3]=OTHER;self.reject('SPACE_BINDING',w.append,a,requested_cursor=None)
 def test_wrong_requested_cursor_rejected(self):
  w=self.walk();a,b=self.pages();w.append(a,requested_cursor=None);self.reject('CURSOR',w.append,b,requested_cursor=ID)
 def test_reused_next_cursor(self):
  w=self.walk();a,b=self.pages();w.append(a,requested_cursor=None);b[4][1]=OTHER;b[4][3]=False;self.reject('CURSOR_REPLAY',w.append,b,requested_cursor=OTHER)
 def test_duplicate_objects_invalidates(self):
  w=self.walk();a,b=self.pages();b[4][2][0][0]=ID;w.append(a,requested_cursor=None);self.reject('DUPLICATE_ITEM',w.append,b,requested_cursor=OTHER)
 def test_entry_budget_is_resource_failure(self):
  w=self.walk(max_items=1);a,b=self.pages();w.append(a,requested_cursor=None);self.reject('RESOURCE_LIMIT',w.append,b,requested_cursor=OTHER)
 def test_page_budget(self):
  w=self.walk(max_pages=1);a,b=self.pages();w.append(a,requested_cursor=None);self.reject('RESOURCE_LIMIT',w.append,b,requested_cursor=OTHER)
 def test_cannot_append_after_complete(self):
  w=self.walk();b=sample(20);w.append(b,requested_cursor=None);self.reject('CLOSED',w.append,b,requested_cursor=None)
 def test_page_bytes_budget(self):
  import inspect
  self.assertIn('max_bytes',inspect.signature(self.mod('paging').InventoryWalk).parameters, 'page byte budget is not implemented')
  w=self.walk(max_bytes=32);self.reject('RESOURCE_LIMIT',w.append,sample(20),requested_cursor=None);self.assertEqual(w.snapshot()['coverage'],'INVALIDATED')
 def test_returned_state_is_detached(self):
  w=self.walk();b=sample(20);w.append(b,requested_cursor=None);v=w.snapshot();v['items'][0][0]=OTHER;self.assertEqual(w.snapshot()['items'][0][0],ID)
 def test_empty_final_snapshot(self):
  w=self.walk();b=sample(20);b[4][2]=[];w.append(b,requested_cursor=None);self.assertEqual(w.snapshot()['coverage'],'PEER_SNAPSHOT_COMPLETE')
 def test_input_mutation_after_append(self):
  w=self.walk();a,b=self.pages();w.append(a,requested_cursor=None);a[4][2][0][0]=OTHER;self.assertEqual(w.snapshot()['items'][0][0],ID)
