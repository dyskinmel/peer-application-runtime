import dataclasses
from auth_support import *
class ActivationTests(AuthTest):
    def test_all_material_activates(self):
        self.require('activation');st,b=active_state(self);self.assertEqual(st.active_epoch,1);self.assertEqual(st.status()['state'],'ACTIVE')
    def test_opaque_seed_claim_is_explicit(self):
        self.require('activation');st,b=active_state(self);self.assertEqual(st.status()['seed_semantics'],'OPAQUE_BYTES_NOT_CRDT_VALIDATED')
    def test_initial_seeds_wait_blocks_write(self):
        self.require('activation');st=self.state();self.reject('EPOCH_PENDING',lambda:st.authorize(self.s.devices[0]['cert'],'write'))
    def test_missing_members_blocks_activation(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);self.reject('MEMBERSHIP_REQUIRED',lambda:activate(st,self.s,b))
    def test_missing_seed_atomic(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);b['seeds']={}
        self.reject('SEED_SET',lambda:activate(st,self.s,b));self.assertIsNone(st.active_epoch)
    def test_corrupt_seed_atomic(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);k=next(iter(b['seeds']));b['seeds'][k]=b['seeds'][k][:-1]+bytes([b['seeds'][k][-1]^1])
        self.reject('SEED_DIGEST',lambda:activate(st,self.s,b));self.assertIsNone(st.active_epoch)
    def test_extra_seed_rejected(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);b['seeds'][h('extra')]=b'extra'
        self.reject('SEED_SET',lambda:activate(st,self.s,b))
    def test_manifest_wrong_root(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);b['manifest']=b['manifest'][:-1]+b'X'
        self.reject('SEED_ROOT',lambda:activate(st,self.s,b))
    def test_missing_package_id(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);b['ids']=[]
        self.reject('CRYPTO_INVALID',lambda:activate(st,self.s,b))
    def test_other_recipient_package(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);b['packages'][self.s.devices[0]['id']]=b['packages'][self.s.devices[1]['id']]
        self.reject('CRYPTO_INVALID',lambda:activate(st,self.s,b))
    def test_wrong_recipient_secret(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);d=self.s.devices[0]
        self.reject('CRYPTO_INVALID',lambda:st.activate(d['cert'],h('bad'),b['packages'][d['id']],b['ids'],b['manifest'],b['seeds']))
    def test_opaque_keeper_cannot_activate(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);self.reject('NOT_AUTHORIZED',lambda:activate(st,self.s,b,2))
    def test_reader_can_activate_cannot_write(self):
        self.require('activation');st,b=active_state(self,index=1);self.assertEqual(st.authorize(self.s.devices[1]['cert'],'read').role,1)
        self.reject('NOT_AUTHORIZED',lambda:st.authorize(self.s.devices[1]['cert'],'write'))
    def test_keeper_retention_does_not_need_seeds(self):
        self.require('activation');st=self.state();self.assertEqual(st.authorize(self.s.devices[2]['cert'],'retain').role,3)
    def test_editor_is_not_implicitly_keeper(self):
        self.require('activation');st,b=active_state(self);self.reject('NOT_AUTHORIZED',lambda:st.authorize(self.s.devices[0]['cert'],'retain'))
    def test_permission_only_retains_original_package_anchor(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages'])
        pp=pages_for(self.s.entries[:2]);c=self.s.next(b['raw']);c[6]=member_root(pp);st.observe(self.s.raw(c));st.provide_membership(pp)
        activate(st,self.s,b);self.assertEqual(st.active_epoch,1);self.assertEqual(st.epoch_anchor.id,control_id(b['raw']))
    def test_rotation_retains_original_package_signer(self):
        self.require('activation');b=epoch_bundle(self.s);st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages'])
        c=self.s.next(b['raw'],4);st.observe(self.s.raw(c,new_seed=self.s.owner1));st.provide_membership(b['pages']);activate(st,self.s,b)
        self.assertEqual(st.authority_public,self.p.sign_public(self.s.owner1));self.assertEqual(st.active_epoch,1)
    def test_content_observation_stops_old_write_immediately(self):
        self.require('activation');st,b=active_state(self);old=st.authorize(self.s.devices[0]['cert'],'write');c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('epoch2'));st.observe(c['raw'])
        self.reject('STALE_DECISION',lambda:st.validate_permit(old));self.reject('MEMBERSHIP_REQUIRED',lambda:st.authorize(self.s.devices[0]['cert'],'write'));self.assertEqual(st.active_epoch,1)
    def test_new_content_after_members_still_waits_seed(self):
        self.require('activation');st,b=active_state(self);c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('epoch2'));st.observe(c['raw']);st.provide_membership(c['pages'])
        self.reject('EPOCH_PENDING',lambda:st.authorize(self.s.devices[0]['cert'],'write'));self.assertEqual(st.active_epoch,1)
    def test_transition_activates_atomically(self):
        self.require('activation');st,b=active_state(self);c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('epoch2'));st.observe(c['raw']);st.provide_membership(c['pages']);activate(st,self.s,c)
        self.assertEqual(st.authorize(self.s.devices[0]['cert'],'write').epoch,2)
    def test_reused_epoch_secret_rejected(self):
        self.require('activation');st,b=active_state(self);c=epoch_bundle(self.s,self.s.next(b['raw'],3),self.s.secret);st.observe(c['raw']);st.provide_membership(c['pages'])
        self.reject('EPOCH_SECRET_REUSED',lambda:activate(st,self.s,c));self.assertEqual(st.active_epoch,1)
    def test_permit_invalidated_by_control(self):
        self.require('activation');st,b=active_state(self);perm=st.authorize(self.s.devices[0]['cert'],'write');st.observe(self.s.raw(self.s.next(b['raw'])));st.provide_membership(b['pages'])
        self.reject('STALE_DECISION',lambda:st.validate_permit(perm))
    def test_permit_not_transferable_between_states(self):
        self.require('activation');st,b=active_state(self);other,_=active_state(self,b);perm=st.authorize(self.s.devices[0]['cert'],'write');self.reject('STALE_DECISION',lambda:other.validate_permit(perm))
    def test_valid_permit(self):
        self.require('activation');st,b=active_state(self);self.assertIsNone(st.validate_permit(st.authorize(self.s.devices[0]['cert'],'write')))
    def test_status_contains_no_secret(self):
        self.require('activation');st,b=active_state(self);self.assertNotIn(b['secret'].hex(),str(st.status()))
    def test_empty_space_seed_set(self):
        self.require('activation');b=epoch_bundle(self.s);m=decode(b['manifest']);m[5]=[];b['manifest']=encode(m);b['seeds']={};b['body'][9]=hashed('auth-local/seed-root',[b['manifest']]);b['raw']=self.s.raw(b['body'])
        st,_=active_state(self,b);self.assertEqual(st.active_epoch,1)
    def test_frozen_chain_cannot_activate(self):
        self.require('activation');st,b=active_state(self);c=self.s.next(b['raw']);st.observe(self.s.raw(c));st.provide_membership(b['pages']);c[7]=h('other')
        self.reject('CONTROL_FORK',lambda:st.observe(self.s.raw(c)));self.reject('CONTROL_FORK',lambda:activate(st,self.s,b))

# Re-sign root with adversarial manifest semantics; cannot be dismissed as a hash mismatch.
def bad_manifest(label,mutate,code):
    def test(self):
        self.require('activation');b=epoch_bundle(self.s);m=decode(b['manifest']);mutate(m);b['manifest']=encode(m);b['body'][9]=hashed('auth-local/seed-root',[b['manifest']]);b['raw']=self.s.raw(b['body'])
        st=self.state(False);st.observe(b['raw']);st.provide_membership(b['pages']);self.reject(code,lambda:activate(st,self.s,b));self.assertIsNone(st.active_epoch)
    return test
for name,mut,code in [
 ('app',lambda m:m.__setitem__(1,'other.example'),'CONTEXT_MISMATCH'),('space',lambda m:m.__setitem__(2,h('other')),'CONTEXT_MISMATCH'),
 ('epoch',lambda m:m.__setitem__(3,2),'CONTEXT_MISMATCH'),('set',lambda m:m.__setitem__(4,b'Z'*16),'CONTEXT_MISMATCH'),
 ('duplicate_object',lambda m:m[5].append(m[5][0]),'SEED_LAYOUT'),('unknown_field',lambda m:m.__setitem__(8,0),'SCHEMA_INVALID'),
 ('wrong_plain_hash',lambda m:m[5][0].__setitem__(4,h('wrong')),'SEED_PLAINTEXT'),
 ('wrong_plain_length',lambda m:m[5][0].__setitem__(3,1),'CRYPTO_INVALID'),
 ('duplicate_cut',lambda m:m.__setitem__(6,[h('a'),h('a')]),'SEED_LAYOUT'),
 ('unsorted_cut',lambda m:m.__setitem__(6,[b'B'*32,b'A'*32]),'SEED_LAYOUT'),
 ('bool_generation',lambda m:m[5][0].__setitem__(2,True),'SCHEMA_INVALID')]:
    setattr(ActivationTests,'test_manifest_'+name,bad_manifest(name,mut,code))

class ActivationRegressionTests(AuthTest):
    def test_same_epoch_different_recipient_key_conflict(self):
        self.require('activation');b=epoch_bundle(self.s);m=decode(b['manifest']);m[5]=[];b['manifest']=encode(m);b['seeds']={};b['body'][9]=hashed('auth-local/seed-root',[b['manifest']])
        d=self.s.devices[1];ctx={0:self.s.app,1:self.s.space,2:1,3:b['body'][10],4:d['id'],5:d['cid'],6:b['body'][6]}
        b['packages'][d['id']]=objects.seal_package(self.p,self.s.owner,self.p.dh_public(d['secret']),ctx,h('conflicting-secret'),random_source=lambda n:h('ephemeral')[:n])
        b['ids']=sorted(objects.package_id(p) for p in b['packages'].values());b['body'][8]=objects.package_root(b['ids']);b['raw']=self.s.raw(b['body'])
        st,_=active_state(self,b);self.reject('EPOCH_SECRET_CONFLICT',lambda:activate(st,self.s,b,1));self.assertEqual(st.active_epoch,1)
    def test_secret_reuse_across_nonadjacent_epochs(self):
        self.require('activation');st,b=active_state(self);c=epoch_bundle(self.s,self.s.next(b['raw'],3),h('epoch2'))
        st.observe(c['raw']);st.provide_membership(c['pages']);activate(st,self.s,c)
        d=epoch_bundle(self.s,self.s.next(c['raw'],3),self.s.secret);st.observe(d['raw']);st.provide_membership(d['pages'])
        self.reject('EPOCH_SECRET_REUSED',lambda:activate(st,self.s,d));self.assertEqual(st.active_epoch,2)
    def test_modified_permit_fields_rejected(self):
        self.require('activation');st,b=active_state(self);permit=st.authorize(self.s.devices[0]['cert'],'write')
        self.reject('STALE_DECISION',lambda:st.validate_permit(dataclasses.replace(permit,operation='read')))
