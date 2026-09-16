import threading
from auth_support import *
class ChainTests(AuthTest):
    def test_control_capacity_cannot_exceed_replay_contract(self):
        chain=self.require('chain')
        self.reject('SCHEMA_INVALID',lambda:chain.AuthorityState(self.p,self.s.app,self.s.space,self.s.genesis,max_controls=1025))

    def test_bootstrap_pinned(self):
        st=self.state(False);self.assertEqual(st.head,self.s.space);self.assertEqual(st.sequence,0);self.assertEqual(st.active_epoch,None)
    def test_wrong_space_pin(self):self.reject('TRUST_ANCHOR',lambda:self.require('chain').AuthorityState(self.p,self.s.app,h('wrong'),self.s.genesis))
    def test_wrong_app_pin(self):self.reject('TRUST_ANCHOR',lambda:self.require('chain').AuthorityState(self.p,'other.example',self.s.space,self.s.genesis))
    def test_bad_genesis_signature(self):
        raw=decode(self.s.genesis);raw[2]=b'0'*64;self.reject('CRYPTO_INVALID',lambda:self.require('chain').AuthorityState(self.p,self.s.app,self.s.space,encode(raw)))
    def test_init_observed_before_membership(self):
        st=self.state(False);self.assertEqual(st.observe(self.s.raw()),'OBSERVED');self.assertEqual(st.sequence,1);self.assertEqual(st.status()['state'],'MEMBERSHIP_PENDING')
    def test_member_material_verified(self):self.assertEqual(self.state().status()['state'],'EPOCH_PENDING')
    def test_same_control_idempotent(self):
        st=self.state();old=st.revision;self.assertEqual(st.observe(self.s.raw()),'DUPLICATE');self.assertEqual(st.revision,old)
    def test_same_members_idempotent(self):
        st=self.state();old=st.revision;self.assertEqual(st.provide_membership(self.s.pages),'DUPLICATE');self.assertEqual(st.revision,old)
    def test_second_control_requires_prior_membership(self):
        st=self.state(False);st.observe(self.s.raw());self.reject('MEMBERSHIP_REQUIRED',lambda:st.observe(self.s.raw(self.s.next(self.s.initial))))
    def test_gap_does_not_advance(self):
        st=self.state();b=self.s.next(self.s.initial);b[2]=3;self.reject('CONTROL_GAP',lambda:st.observe(self.s.raw(b)));self.assertEqual(st.sequence,1)
    def test_wrong_parent_does_not_freeze(self):
        st=self.state();b=self.s.next(self.s.initial);b[4]=h('bad');self.reject('CONTROL_PARENT',lambda:st.observe(self.s.raw(b)));self.assertFalse(st.frozen)
    def test_wrong_signer_does_not_freeze(self):
        st=self.state();b=self.s.next(self.s.initial);b[11]=self.p.sign_public(self.s.owner1)
        self.reject('AUTHORITY_MISMATCH',lambda:st.observe(self.s.raw(b,self.s.owner1)));self.assertFalse(st.frozen)
    def test_bad_signature_no_state_change(self):
        st=self.state();b=decode(self.s.raw(self.s.next(self.s.initial)));b[1]=b'0'*64;old=st.head
        self.reject('CRYPTO_INVALID',lambda:st.observe(encode(b)));self.assertEqual(st.head,old)
    def test_permission_keeper_changes_without_rekey(self):
        st=self.state();e=self.s.entries[:2];pp=pages_for(e);b=self.s.next(self.s.initial);b[6]=member_root(pp)
        st.observe(self.s.raw(b));st.provide_membership(pp);self.assertEqual(st.epoch,1);self.assertEqual(st.sequence,2)
    def test_permission_reader_change_quarantines(self):
        st=self.state();pp=pages_for(self.s.entries[1:]);b=self.s.next(self.s.initial);b[6]=member_root(pp);st.observe(self.s.raw(b))
        self.reject('CONTENT_MEMBERSHIP_CHANGED',lambda:st.provide_membership(pp));self.assertEqual(st.status()['state'],'CONTROL_INVALID')
    def test_permission_role_change_quarantines(self):
        st=self.state();e=decode(self.s.pages[0]);e[0][2]=1 if e[0][2]==2 else 2;pp=pages_for(e);b=self.s.next(self.s.initial);b[6]=member_root(pp);st.observe(self.s.raw(b))
        self.reject('CONTENT_MEMBERSHIP_CHANGED',lambda:st.provide_membership(pp))
    def test_membership_wrong_root_can_retry(self):
        st=self.state(False);st.observe(self.s.raw());self.reject('MEMBERSHIP_ROOT',lambda:st.provide_membership([]));st.provide_membership(self.s.pages);self.assertEqual(st.status()['state'],'EPOCH_PENDING')
    def test_content_transition_increments_epoch(self):
        st=self.state();b=self.s.next(self.s.initial,3);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);self.assertEqual(st.epoch,2)
    def test_content_transition_allows_removed_reader(self):
        st=self.state();b=self.s.next(self.s.initial,3);pp=pages_for(self.s.entries[:1]);b[6]=member_root(pp);st.observe(self.s.raw(b));st.provide_membership(pp);self.assertEqual(len(st.membership.members),1)
    def test_rotation_needs_both_signatures(self):
        st=self.state();b=self.s.next(self.s.initial,4);self.reject('ROTATION_PROOF',lambda:st.observe(self.s.raw(b)))
    def test_rotation_new_authority_only_next_entry(self):
        st=self.state();b=self.s.next(self.s.initial,4);raw=self.s.raw(b,new_seed=self.s.owner1);st.observe(raw);st.provide_membership(self.s.pages)
        self.assertEqual(st.authority_public,self.p.sign_public(self.s.owner1));self.assertEqual(st.space_id,self.s.space)
        c=self.s.next(raw,5);c[11]=self.p.sign_public(self.s.owner1);c[12]=None;st.observe(self.s.raw(c,self.s.owner1));st.provide_membership(self.s.pages);self.assertEqual(st.sequence,3)
    def test_rotation_old_authority_rejected_later(self):
        st=self.state();b=self.s.next(self.s.initial,4);raw=self.s.raw(b,new_seed=self.s.owner1);st.observe(raw);st.provide_membership(self.s.pages)
        c=self.s.next(raw,5);c[12]=None;self.reject('AUTHORITY_MISMATCH',lambda:st.observe(self.s.raw(c)))
    def test_rotation_wrong_possession_domain(self):
        st=self.state();b=self.s.next(self.s.initial,4);o=decode(self.s.raw(b,new_seed=self.s.owner1));o[2]=self.p.sign(self.s.owner1,domain('control-sign',[o[0]]))
        self.reject('CRYPTO_INVALID',lambda:st.observe(encode(o)))
    def test_latest_fork_freezes_and_retains_both(self):
        st=self.state();b=self.s.next(self.s.initial);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);c=dict(b);c[7]=h('different')
        self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(c)));self.assertTrue(st.frozen);self.assertEqual(len(st.fork_evidence),2)
    def test_historical_fork_detected(self):
        st=self.state();b=self.s.next(self.s.initial);br=self.s.raw(b);st.observe(br);st.provide_membership(self.s.pages);c=self.s.next(br,5);st.observe(self.s.raw(c));st.provide_membership(self.s.pages)
        b[7]=h('fork');self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(b)));self.assertTrue(st.frozen)
    def test_invalid_fork_signature_does_not_freeze(self):
        st=self.state();b=self.s.next(self.s.initial);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);b[7]=h('fork');raw=decode(self.s.raw(b));raw[1]=b'0'*64
        self.reject('CRYPTO_INVALID',lambda:st.observe(encode(raw)));self.assertFalse(st.frozen)
    def test_freeze_has_no_auto_winner(self):
        st=self.state();b=self.s.next(self.s.initial);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);b[7]=h('fork')
        self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(b)));self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(self.s.next(b,5))))
    def test_control_snapshot_does_not_alias_input(self):
        st=self.state();b=self.s.next(self.s.initial);raw=self.s.raw(b);st.observe(raw);b[3]=99;self.assertEqual(st.epoch,1)
    def test_thread_affinity(self):
        st=self.state();out=[]
        def run():
            try:st.observe(self.s.raw())
            except Exception as e:out.append(getattr(e,'code',None))
        t=threading.Thread(target=run);t.start();t.join();self.assertEqual(out,['WRONG_THREAD'])
    def test_history_budget_is_explicit(self):
        st=self.require('chain').AuthorityState(self.p,self.s.app,self.s.space,self.s.genesis,max_controls=1);st.observe(self.s.raw());st.provide_membership(self.s.pages)
        self.reject('RESOURCE_BLOCKED',lambda:st.observe(self.s.raw(self.s.next(self.s.initial))))

# Each mutation is signed by the correct owner; these are semantic rejections, not signature failures.
def altered(name,action,key,value,code):
    def test(self):
        st=self.state();b=self.s.next(self.s.initial,action);b[key]=value(self) if callable(value) else value
        raw=self.s.raw(b,new_seed=self.s.owner1 if action==4 else None)
        self.reject(code,lambda:st.observe(raw))
    return test
for name,action,key,value,code in [
 ('epoch_skipped',3,3,3,'EPOCH_SEQUENCE'),('epoch_not_changed',3,3,1,'EPOCH_SEQUENCE'),
 ('permission_epoch',2,3,2,'EPOCH_SEQUENCE'),('permission_package',2,8,h('bad'),'ROOT_CHANGED'),
 ('permission_seed',2,9,h('bad'),'ROOT_CHANGED'),('permission_set',2,10,b'Z'*16,'ROOT_CHANGED'),
 ('permission_feature',2,13,h('bad'),'ROOT_CHANGED'),('checkpoint_members',5,6,h('bad'),'ROOT_CHANGED'),
 ('checkpoint_resource',5,7,h('bad'),'ROOT_CHANGED'),('rotation_members',4,6,h('bad'),'ROOT_CHANGED'),
 ('rotation_to_same',4,12,lambda s:s.p.sign_public(s.s.owner),'ROTATION_PROOF'),
 ('transition_set_reuse',3,10,lambda s:s.s.initial[10],'EPOCH_MATERIAL_REUSED'),
 ('transition_seed_reuse',3,9,lambda s:s.s.initial[9],'EPOCH_MATERIAL_REUSED'),
 ('transition_package_reuse',3,8,lambda s:s.s.initial[8],'EPOCH_MATERIAL_REUSED'),
 ('null_package',3,8,None,'MISSING_EPOCH_MATERIAL'),('second_init',1,5,1,'ACTION_INVALID'),
 ('other_space',2,1,h('other'),'CONTEXT_MISMATCH'),('other_app',2,0,'other.example','CONTEXT_MISMATCH')]:
    setattr(ChainTests,'test_reject_'+name,altered(name,action,key,value,code))

class ForkBudgetRegressionTests(AuthTest):
    def test_valid_fork_freezes_even_at_history_budget(self):
        from unittest.mock import patch
        st=self.state();b=self.s.next(self.s.initial);st.observe(self.s.raw(b));st.provide_membership(self.s.pages);b[7]=h('fork-at-limit')
        with patch.object(self.require('chain'),'MAX_HISTORY_BYTES',st._event_bytes+1):
            self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(b)))
        self.assertTrue(st.frozen);self.assertEqual(len(st.fork_evidence),2)
