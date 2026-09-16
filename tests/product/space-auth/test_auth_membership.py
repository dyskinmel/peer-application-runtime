import dataclasses
from auth_support import *
class MembershipTests(AuthTest):
    def test_complete_root(self):
        m=self.require('membership');v=m.verify_membership(self.s.root,self.s.pages)
        self.assertEqual(v.root,self.s.root);self.assertEqual(len(v.members),3)
    def test_builder_is_canonical(self):
        m=self.require('membership');self.assertEqual(m.build_membership(list(reversed(self.s.entries))),self.s.pages)
    def test_wrong_root(self):self.reject('MEMBERSHIP_ROOT',lambda:self.require('membership').verify_membership(h('bad'),self.s.pages))
    def test_missing_page(self):self.reject('MEMBERSHIP_ROOT',lambda:self.require('membership').verify_membership(self.s.root,[]))
    def test_empty_membership(self):
        m=self.require('membership');self.assertEqual(m.verify_membership(member_root([]),[]).members,())
    def test_duplicate_member(self):
        pp=[encode([self.s.entries[0],self.s.entries[0]])];self.reject('MEMBERSHIP_ORDER',lambda:self.require('membership').verify_membership(member_root(pp),pp))
    def test_unsorted_members(self):
        pp=[encode(list(reversed(decode(self.s.pages[0]))))];self.reject('MEMBERSHIP_ORDER',lambda:self.require('membership').verify_membership(member_root(pp),pp))
    def test_empty_page_not_alternate_empty_root(self):self.reject('MEMBERSHIP_LAYOUT',lambda:self.require('membership').verify_membership(member_root([encode([])]),[encode([])]))
    def test_short_nonfinal_page(self):
        pp=[encode([self.s.entries[0]]),encode([self.s.entries[1]])];self.reject('MEMBERSHIP_LAYOUT',lambda:self.require('membership').verify_membership(member_root(pp),pp))
    def test_65_entries_page_boundary(self):
        e=[{0:i.to_bytes(32,'big'),1:h(str(i)),2:3} for i in range(65)];pp=pages_for(e);m=self.require('membership')
        self.assertEqual(m.build_membership(e),pp);self.assertEqual(len(m.verify_membership(member_root(pp),pp).members),65)
    def test_swapped_pages_rejected(self):
        e=[{0:i.to_bytes(32,'big'),1:h(str(i)),2:3} for i in range(128)];pp=pages_for(e)
        self.reject('MEMBERSHIP_ORDER',lambda:self.require('membership').verify_membership(member_root(pp[::-1]),pp[::-1]))
    def test_member_limit(self):
        e=[{0:i.to_bytes(32,'big'),1:h(str(i)),2:3} for i in range(257)]
        self.reject('RESOURCE_BLOCKED',lambda:self.require('membership').build_membership(e))
    def test_member_immutable(self):
        v=self.require('membership').verify_membership(self.s.root,self.s.pages)
        with self.assertRaises(dataclasses.FrozenInstanceError):v.members[0].role=2
    def test_valid_certificate_bound(self):
        m=self.require('membership');v=m.verify_membership(self.s.root,self.s.pages);d=self.s.devices[0]
        b=m.member_certificate(self.p,self.s.app,v,d['cert']);self.assertEqual(b[3],self.p.sign_public(d['seed']))
    def test_certificate_not_member(self):
        m=self.require('membership');d=self.s.devices[0];v=m.verify_membership(member_root([]),[])
        self.reject('NOT_AUTHORIZED',lambda:m.member_certificate(self.p,self.s.app,v,d['cert']))
    def test_certificate_reissue_not_silent(self):
        m=self.require('membership');d=self.s.devices[0];o=decode(d['cert']);b=decode(o[0]);b[5]=h('newserial')[:16]
        raw=objects._signed(self.p,h('account-0'),'certificate-sign',b);v=m.verify_membership(self.s.root,self.s.pages)
        self.reject('CERTIFICATE_BINDING',lambda:m.member_certificate(self.p,self.s.app,v,raw))
    def test_certificate_wrong_device_digest(self):
        e=[{0:h('wrongid'),1:self.s.devices[0]['cid'],2:2}];pp=pages_for(e);m=self.require('membership');v=m.verify_membership(member_root(pp),pp)
        self.reject('NOT_AUTHORIZED',lambda:m.member_certificate(self.p,self.s.app,v,self.s.devices[0]['cert']))
    def test_certificate_signature_required_even_when_digest_matches(self):
        d=self.s.devices[0];o=decode(d['cert']);o[2]=b'0'*64;raw=encode(o);e=[{0:d['id'],1:objects.certificate_id(raw),2:2}];pp=pages_for(e)
        m=self.require('membership');v=m.verify_membership(member_root(pp),pp)
        self.reject('CRYPTO_INVALID',lambda:m.member_certificate(self.p,self.s.app,v,raw))
    def test_content_projection_excludes_keeper(self):
        v=self.require('membership').verify_membership(self.s.root,self.s.pages);self.assertEqual(len(v.content_members),2)
    def test_view_no_alias_to_input(self):
        m=self.require('membership');e=list(self.s.entries);pp=m.build_membership(e);v=m.verify_membership(self.s.root,pp);e[0][2]=3;pp.clear();self.assertEqual(len(v.content_members),2)

def malformed(label,entry):
    def test(self):
        pp=[encode([entry])];self.reject('SCHEMA_INVALID',lambda:self.require('membership').verify_membership(member_root(pp),pp))
    test.__name__='test_bad_member_'+label;return test
for label,entry in [('short_device',{0:b'x',1:h('c'),2:1}),('short_cert',{0:h('d'),1:b'x',2:1}),('bool_role',{0:h('d'),1:h('c'),2:True}),('unknown_role',{0:h('d'),1:h('c'),2:4}),('extra',{0:h('d'),1:h('c'),2:1,3:0}),('missing',{0:h('d'),1:h('c')})]:
    setattr(MembershipTests,'test_bad_member_'+label,malformed(label,entry))
