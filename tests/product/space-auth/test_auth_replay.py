from auth_support import *
class ReplayTests(AuthTest):
    def export(self,st):
        m=self.require('replay');raw=m.export_public_replay(st);digest=hashed('auth-local/replay',[raw]);return m,raw,digest
    def restore(self,m,raw,digest,st,**kw):return m.restore_public_replay(self.p,self.s.app,self.s.space,kw.get('head',st.head),digest,raw,minimum_sequence=kw.get('seq',st.sequence))
    def test_verified_history_replay(self):
        st=self.state();m,raw,d=self.export(st);other=self.restore(m,raw,d,st);self.assertEqual(other.head,st.head);self.assertEqual(other.membership,st.membership)
    def test_active_secrets_not_serialized(self):
        st,b=active_state(self);m,raw,d=self.export(st);self.assertNotIn(b['secret'],raw);self.assertNotIn(self.s.owner,raw);self.assertNotIn(self.s.devices[0]['secret'],raw)
        other=self.restore(m,raw,d,st);self.assertIsNone(other.active_epoch);self.reject('EPOCH_PENDING',lambda:other.authorize(self.s.devices[0]['cert'],'write'))
    def test_replay_can_reactivate_after_material_revalidation(self):
        st,b=active_state(self);m,raw,d=self.export(st);other=self.restore(m,raw,d,st);activate(other,self.s,b);self.assertEqual(other.active_epoch,1)
    def test_wrong_pinned_digest(self):
        st=self.state();m,raw,d=self.export(st);self.reject('REPLAY_DIGEST',lambda:self.restore(m,raw,h('wrong'),st))
    def test_wrong_pinned_head(self):
        st=self.state();m,raw,d=self.export(st);self.reject('REPLAY_STALE',lambda:self.restore(m,raw,d,st,head=h('wrong')))
    def test_sequence_floor(self):
        st=self.state();m,raw,d=self.export(st);self.reject('REPLAY_STALE',lambda:self.restore(m,raw,d,st,seq=2))
    def test_body_corruption_rejected(self):
        st=self.state();m,raw,d=self.export(st);other=raw[:-1]+bytes([raw[-1]^1]);self.reject('REPLAY_DIGEST',lambda:self.restore(m,other,d,st))
    def test_replay_signature_not_replaced_by_digest(self):
        st=self.state();m,raw,d=self.export(st);v=decode(raw);o=decode(v[4][0][1]);o[1]=b'0'*64;v[4][0][1]=encode(o);raw=encode(v);d=hashed('auth-local/replay',[raw])
        self.reject('CRYPTO_INVALID',lambda:self.restore(m,raw,d,st))
    def test_fork_evidence_survives_replay(self):
        st=self.state();b=self.s.next(self.s.initial);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);b[7]=h('fork');self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(b)))
        m,raw,d=self.export(st);other=self.restore(m,raw,d,st);self.assertTrue(other.frozen);self.assertEqual(other.fork_evidence,st.fork_evidence)
    def test_invalid_authority_policy_survives_replay(self):
        st=self.state();pp=pages_for(self.s.entries[1:]);b=self.s.next(self.s.initial);b[6]=member_root(pp);st.observe(self.s.raw(b));self.reject('CONTENT_MEMBERSHIP_CHANGED',lambda:st.provide_membership(pp))
        m,raw,d=self.export(st);other=self.restore(m,raw,d,st);self.assertEqual(other.status()['state'],'CONTROL_INVALID')
    def test_missing_member_event_restores_pending_not_ready(self):
        st=self.state(False);st.observe(self.s.raw());m,raw,d=self.export(st);other=self.restore(m,raw,d,st);self.assertEqual(other.status()['state'],'MEMBERSHIP_PENDING')
    def test_export_is_deterministic(self):
        st=self.state();m,raw,d=self.export(st);self.assertEqual(m.export_public_replay(st),raw)
    def test_replay_unknown_event(self):
        st=self.state();m,raw,d=self.export(st);v=decode(raw);v[4].append([3,b'x']);raw=encode(v);d=hashed('auth-local/replay',[raw]);self.reject('REPLAY_SCHEMA',lambda:self.restore(m,raw,d,st))
    def test_replay_does_not_grant_authority_secret(self):
        st=self.state();m,raw,d=self.export(st);other=self.restore(m,raw,d,st);self.assertEqual(other.authority_public,st.authority_public);self.assertFalse(hasattr(other,'authority_secret'))
