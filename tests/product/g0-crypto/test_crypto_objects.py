"""Context substitution and key authority rejection, not membership qualification."""
from crypto_support import CryptoTest
from par_wire.codec import encode,decode
from par_crypto.primitives import hashed

EPOCH=b'E'*32; SIGN=b'S'*32; ROOTKEY=b'A'*32; RECIPIENT=b'R'*32
PAYLOAD=b'public synthetic change\0\xf0\x9f\x8e\xb5'
def header(p):
    return {0:'org.example.notes',1:b'w'*32,2:1,3:b'o'*32,4:1,
        5:hashed('device-id',['org.example.notes',p.sign_public(SIGN)]),6:b'g'*16,7:1,8:None,
        9:b'd'*32,10:[],11:len(PAYLOAD),12:b'c'*32,13:b'h'*32,14:1,15:0}
def context(p):
    return {0:'org.example.notes',1:b'w'*32,2:1,3:b'x'*16,
        4:hashed('device-id',['org.example.notes',p.sign_public(SIGN)]),5:b'c'*32,6:b'm'*32}
class ObjectTests(CryptoTest):
    def setUp(self):
        super().setUp();self.m=self.require('objects');self.h=header(self.p)
    def seal(self,h=None):return self.m.seal_change(self.p,EPOCH,SIGN,self.h if h is None else h,PAYLOAD,b'n'*24)
    def test_envelope_roundtrip(self):
        sealed=self.seal();self.assertEqual(self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),self.h,sealed),PAYLOAD)
        self.assertEqual(self.m.envelope_id(sealed),hashed('envelope-id',[sealed]))
    def test_envelope_no_payload_in_serialized_bytes(self):self.assertNotIn(PAYLOAD,self.seal())
    def test_envelope_exact_repeat_deterministic_lowlevel(self):self.assertEqual(self.seal(),self.seal())
    def test_envelope_wrong_key(self):self.reject('AEAD_INVALID',lambda:self.m.open_change(self.p,b'Q'*32,self.p.sign_public(SIGN),self.h,self.seal()))
    def test_envelope_wrong_signer(self):self.reject('AUTHOR_MISMATCH',lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(ROOTKEY),self.h,self.seal()))
    def test_envelope_claimed_length(self):
        h=dict(self.h);h[11]+=1;self.reject('LENGTH_MISMATCH',lambda:self.seal(h))
    def test_envelope_missing_field(self):
        h=dict(self.h);del h[13];self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_extra_field(self):
        h=dict(self.h);h[16]=0;self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_zero_sequence(self):
        h=dict(self.h);h[7]=0;self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_duplicate_deps(self):
        h=dict(self.h);h[10]=[b'd'*32,b'd'*32];self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_non_domain_app(self):
        h=dict(self.h);h[0]='not-an-app';self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_unknown_codec(self):
        h=dict(self.h);h[14]=8;self.reject('OBJECT_SCHEMA',lambda:self.seal(h))
    def test_envelope_oversize(self):self.reject(None,lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),self.h,b'x'*786433))
    def test_envelope_trailing_bytes(self):self.reject('OBJECT_SCHEMA',lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),self.h,self.seal()+b'\0'))
    def test_envelope_invalid_expected_header(self):self.reject('OBJECT_SCHEMA',lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),{},self.seal()))
    def test_envelope_signed_noncanonical_header(self):
        x=decode(self.seal());x[0]=b'\xb8\x10'+x[0][1:]
        from par_crypto.primitives import domain
        x[3]=self.p.sign(SIGN,domain('envelope-sign',[x[0],x[1],x[2]]))
        self.reject('OBJECT_SCHEMA',lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),self.h,encode(x)))
    def test_empty_change_payload(self):
        h=dict(self.h);h[11]=0;s=self.m.seal_change(self.p,EPOCH,SIGN,h,b'',b'n'*24)
        self.assertEqual(self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),h,s),b'')
    def test_block_roundtrip(self):
        h={0:self.h[0],1:self.h[1],2:1,3:self.h[3],4:3,5:8,6:0,7:len(PAYLOAD)}
        b=self.m.seal_block(self.p,EPOCH,h,PAYLOAD,b'n'*24)
        self.assertEqual(self.m.open_block(self.p,EPOCH,h,b),PAYLOAD)
        self.assertEqual(self.m.block_id(b),hashed('block-id',[b]))
    def test_block_wrong_chunk(self):
        h={0:self.h[0],1:self.h[1],2:1,3:self.h[3],4:3,5:8,6:0,7:len(PAYLOAD)}
        b=self.m.seal_block(self.p,EPOCH,h,PAYLOAD,b'n'*24);h[5]=9
        self.reject('CONTEXT_MISMATCH',lambda:self.m.open_block(self.p,EPOCH,h,b))
    def test_block_modified_ciphertext(self):
        h={0:self.h[0],1:self.h[1],2:1,3:self.h[3],4:3,5:0,6:0,7:len(PAYLOAD)}
        b=decode(self.m.seal_block(self.p,EPOCH,h,PAYLOAD,b'n'*24));b[2]=b[2][:-1]+bytes([b[2][-1]^1])
        self.reject('AEAD_INVALID',lambda:self.m.open_block(self.p,EPOCH,h,encode(b)))
    def test_certificate_roundtrip(self):
        c=self.m.create_certificate(self.p,ROOTKEY,self.h[0],self.p.sign_public(SIGN),self.p.dh_public(RECIPIENT),b's'*16)
        b=self.m.verify_certificate(self.p,self.h[0],self.p.sign_public(ROOTKEY),c)
        self.assertEqual(b[3],self.p.sign_public(SIGN));self.assertEqual(b[4],self.p.dh_public(RECIPIENT))
    def test_certificate_wrong_trust_anchor(self):
        c=self.m.create_certificate(self.p,ROOTKEY,self.h[0],self.p.sign_public(SIGN),self.p.dh_public(RECIPIENT),b's'*16)
        self.reject('SIGNER_MISMATCH',lambda:self.m.verify_certificate(self.p,self.h[0],self.p.sign_public(SIGN),c))
    def test_certificate_wrong_app(self):
        c=self.m.create_certificate(self.p,ROOTKEY,self.h[0],self.p.sign_public(SIGN),self.p.dh_public(RECIPIENT),b's'*16)
        self.reject('CONTEXT_MISMATCH',lambda:self.m.verify_certificate(self.p,'org.other.notes',self.p.sign_public(ROOTKEY),c))
    def test_certificate_key_role_reuse(self):
        self.reject('KEY_ROLE_REUSE',lambda:self.m.create_certificate(self.p,ROOTKEY,self.h[0],self.p.sign_public(ROOTKEY),self.p.dh_public(RECIPIENT),b's'*16))
    def test_package_roundtrip(self):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH)
        ids=[self.m.package_id(b)];r=self.m.package_root(ids)
        self.assertEqual(self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),c,b,ids,r),EPOCH)
    def test_package_root_order_independent(self):self.assertEqual(self.m.package_root([b'a'*32,b'b'*32]),self.m.package_root([b'b'*32,b'a'*32]))
    def test_package_root_duplicate(self):self.reject('PACKAGE_ROOT_INVALID',lambda:self.m.package_root([b'a'*32,b'a'*32]))
    def test_package_root_empty(self):self.reject('PACKAGE_ROOT_INVALID',lambda:self.m.package_root([]))
    def test_package_root_limit(self):self.reject('PACKAGE_ROOT_INVALID',lambda:self.m.package_root([i.to_bytes(32,'big') for i in range(1025)]))
    def test_package_root_wrong(self):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH);ids=[self.m.package_id(b)]
        self.reject('PACKAGE_ROOT_INVALID',lambda:self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),c,b,ids,b'X'*32))
    def test_package_not_in_root(self):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH);ids=[b'X'*32]
        self.reject('PACKAGE_ROOT_INVALID',lambda:self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),c,b,ids,self.m.package_root(ids)))
    def test_package_wrong_recipient_secret(self):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH);ids=[self.m.package_id(b)]
        self.reject('AEAD_INVALID',lambda:self.m.open_package(self.p,b'X'*32,self.p.sign_public(ROOTKEY),c,b,ids,self.m.package_root(ids)))
    def test_package_wrong_authority(self):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH);ids=[self.m.package_id(b)]
        self.reject('SIGNER_MISMATCH',lambda:self.m.open_package(self.p,RECIPIENT,self.p.sign_public(SIGN),c,b,ids,self.m.package_root(ids)))
    def test_package_modified_signature(self):
        c=context(self.p);o=decode(self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH));o[2]=b'\0'*64;b=encode(o);ids=[self.m.package_id(b)]
        self.reject('SIGNATURE_INVALID',lambda:self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),c,b,ids,self.m.package_root(ids)))

def field_case(key):
    def test(self):
        altered=dict(self.h)
        v=altered[key]
        altered[key]= ('org.other.notes' if key==0 else b'P'*32 if v is None else [b'p'*32] if type(v) is list else v+1 if type(v) is int else bytes([v[0]^1])+v[1:])
        self.reject(None,lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),altered,self.seal()))
    return test
for i in range(16):setattr(ObjectTests,f'test_change_context_field_{i:02d}',field_case(i))
for key in (1,2,3):
    def mutate(self,k=key):
        o=decode(self.seal());o[k]=bytes([o[k][0]^1])+o[k][1:]
        self.reject('SIGNATURE_INVALID',lambda:self.m.open_change(self.p,EPOCH,self.p.sign_public(SIGN),self.h,encode(o)))
    setattr(ObjectTests,f'test_change_tampered_outer_{key}',mutate)
for key in range(7):
    def mutate(self,k=key):
        c=context(self.p);b=self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),c,EPOCH);ids=[self.m.package_id(b)]
        other=dict(c);v=other[k];other[k]='org.other.notes' if k==0 else v+1 if type(v) is int else bytes([v[0]^1])+v[1:]
        self.reject('CONTEXT_MISMATCH',lambda:self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),other,b,ids,self.m.package_root(ids)))
    setattr(ObjectTests,f'test_package_context_field_{key}',mutate)

class FrozenObjectVectors(CryptoTest):
    def setUp(self):
        super().setUp();self.m=self.require('objects')
        from crypto_support import FIX
        self.path=FIX/'composed-candidate.json'
        self.assertTrue(self.path.is_file(),'frozen composed-object corpus has not been created')
        import json
        self.v=json.loads(self.path.read_text())
    def test_fixed_envelope(self):self.assertEqual(self.m.seal_change(self.p,EPOCH,SIGN,header(self.p),PAYLOAD,b'n'*24).hex(),self.v['envelope_hex'])
    def test_fixed_envelope_id(self):self.assertEqual(self.m.envelope_id(bytes.fromhex(self.v['envelope_hex'])).hex(),self.v['envelope_id_hex'])
    def test_fixed_certificate(self):
        self.assertEqual(self.m.create_certificate(self.p,ROOTKEY,'org.example.notes',self.p.sign_public(SIGN),self.p.dh_public(RECIPIENT),b's'*16).hex(),self.v['certificate_hex'])
    def test_fixed_package(self):
        self.assertEqual(self.m.seal_package(self.p,ROOTKEY,self.p.dh_public(RECIPIENT),context(self.p),EPOCH,random_source=lambda n:b'e'*n).hex(),self.v['package_hex'])
    def test_fixed_package_root(self):self.assertEqual(self.m.package_root([bytes.fromhex(self.v['package_id_hex'])]).hex(),self.v['package_root_hex'])
    def test_fixed_package_opens(self):
        raw=bytes.fromhex(self.v['package_hex']);r=bytes.fromhex(self.v['package_root_hex']);ids=[bytes.fromhex(self.v['package_id_hex'])]
        self.assertEqual(self.m.open_package(self.p,RECIPIENT,self.p.sign_public(ROOTKEY),context(self.p),raw,ids,r),EPOCH)
    def test_fixed_block(self):
        h={0:'org.example.notes',1:b'w'*32,2:1,3:b'o'*32,4:3,5:8,6:0,7:len(PAYLOAD)}
        self.assertEqual(self.m.seal_block(self.p,EPOCH,h,PAYLOAD,b'n'*24).hex(),self.v['block_hex'])
    def test_fixture_is_explicitly_unqualified(self):
        self.assertFalse(self.v['independently_reviewed']);self.assertEqual(self.v['classification'],'PUBLIC_SYNTHETIC_REGRESSION_VECTORS')
