import hashlib, json, unittest
from pathlib import Path
from crypto_support import CryptoTest, fixture, ROOT, PIN

class PrimitiveTests(CryptoTest):
    def test_provider_exact_image(self):
        pin=json.loads(PIN.read_text());self.assertEqual(self.p.identity['sha256'],pin['sha256'])
        self.assertEqual(self.p.identity['version'],pin['version']);self.assertFalse(self.p.identity['security_qualified'])
    def test_provider_wrong_hash_rejected(self):
        pin=json.loads(PIN.read_text());pin['sha256']='0'*64
        self.reject('PROVIDER_PIN_MISMATCH',lambda:self.provider_module.SodiumProvider(pin,allow_legacy_experiment=True))
    def test_old_provider_requires_explicit_consent(self):
        self.reject('PROVIDER_UPGRADE_REQUIRED',lambda:self.provider_module.SodiumProvider(json.loads(PIN.read_text())))
    def test_relative_library_path_rejected(self):
        pin=json.loads(PIN.read_text());pin['candidate_paths']=['libsodium.so.23']
        self.reject('PROVIDER_PATH',lambda:self.provider_module.SodiumProvider(pin,allow_legacy_experiment=True))
    def test_ed25519_rfc8032_known_answer(self):
        v=json.loads((ROOT/'baseline/spec-00.02.00/fixtures/primitive-kats.json').read_text())['ed25519']
        b=lambda k:bytes.fromhex(v[k]);pk=self.p.sign_public(b('secret_seed_hex'))
        self.assertEqual(pk,b('public_key_hex'));sig=self.p.sign(b('secret_seed_hex'),b('message_hex'))
        self.assertEqual(sig,b('signature_hex'));self.p.verify(pk,b('message_hex'),sig)
    def test_ed25519_bit_flip(self):
        seed=b's'*32;sig=self.p.sign(seed,b'a');self.reject('SIGNATURE_INVALID',lambda:self.p.verify(self.p.sign_public(seed),b'b',sig))
    def test_ed25519_noncanonical_s(self):
        seed=b's'*32;sig=self.p.sign(seed,b'a');L=2**252+27742317777372353535851937790883648493
        changed=sig[:32]+(int.from_bytes(sig[32:],'little')+L).to_bytes(32,'little')
        self.reject('SIGNATURE_INVALID',lambda:self.p.verify(self.p.sign_public(seed),b'a',changed))
    def test_ed25519_identity_forgery(self):
        identity=b'\x01'+b'\0'*31
        self.reject('SIGNATURE_INVALID',lambda:self.p.verify(identity,b'',identity+b'\0'*32))
    def test_hkdf_rfc5869(self):
        m=self.require('primitives');v=json.loads((ROOT/'baseline/spec-00.02.00/fixtures/primitive-kats.json').read_text())['hkdf_sha256'];b=lambda k:bytes.fromhex(v[k])
        prk=m.hkdf_extract(b('salt_hex'),b('ikm_hex'));self.assertEqual(prk,b('prk_hex'))
        self.assertEqual(m.hkdf_expand(prk,b('info_hex'),v['length']),b('okm_hex'))
    def test_hkdf_length_bounds(self):
        m=self.require('primitives')
        self.assertEqual(m.hkdf_expand(b'a'*32,b'',0),b'')
        self.assertEqual(len(m.hkdf_expand(b'a'*32,b'',8160)),8160)
        for n in [-1,8161,True]:self.reject('INVALID_INPUT',lambda:m.hkdf_expand(b'a'*32,b'',n))
    def test_xchacha_draft_known_answer(self):
        v=fixture('xchacha.json');b=lambda k:bytes.fromhex(v[k])
        ct=self.p.seal(b('key'),b('nonce'),b('aad'),b('plaintext'))
        self.assertEqual(ct,b('ciphertext'));self.assertEqual(self.p.open(b('key'),b('nonce'),b('aad'),ct),b('plaintext'))
    def test_xchacha_empty_roundtrip(self):
        c=self.p.seal(b'k'*32,b'n'*24,b'',b'');self.assertEqual(len(c),16);self.assertEqual(self.p.open(b'k'*32,b'n'*24,b'',c),b'')
    def test_xchacha_modified_tag(self):
        c=self.p.seal(b'k'*32,b'n'*24,b'a',b'p');c=c[:-1]+bytes([c[-1]^1])
        self.reject('AEAD_INVALID',lambda:self.p.open(b'k'*32,b'n'*24,b'a',c))
    def test_xchacha_aad_binding(self):
        c=self.p.seal(b'k'*32,b'n'*24,b'a',b'p');self.reject('AEAD_INVALID',lambda:self.p.open(b'k'*32,b'n'*24,b'b',c))
    def test_x25519_rfc9180_public(self):
        v=fixture('hpke-base.json');self.assertEqual(self.p.dh_public(bytes.fromhex(v['skRm'])),bytes.fromhex(v['pkRm']))
    def test_x25519_low_order_rejected(self):
        for pk in [b'\0'*32,b'\x01'+b'\0'*31]:self.reject('KEM_INVALID',lambda:self.p.dh(b's'*32,pk))
    def test_rng_failure_is_fail_closed(self):
        m=self.require('primitives')
        def broken(n):raise OSError('sensitive unavailable')
        self.reject('RNG_FAILURE',lambda:m.random_bytes(24,broken))
    def test_rng_wrong_length(self):
        self.reject('RNG_FAILURE',lambda:self.require('primitives').random_bytes(24,lambda n:b'x'))
    def test_error_has_no_key(self):
        key=b'SECRET'*6
        try:self.p.seal(key,b'n'*24,b'',b'PLAINTEXT')
        except Exception as e:
            self.assertNotIn('SECRET',str(e));self.assertNotIn('PLAINTEXT',str(e))
        else:self.fail('invalid key accepted')

def make_length(method,arg,size):
    def test(self):
        good={'sign':[b's'*32,b'data'],'verify':[self.p.sign_public(b's'*32),b'data',self.p.sign(b's'*32,b'data')],
              'seal':[b'k'*32,b'n'*24,b'a',b'p'],'open':[b'k'*32,b'n'*24,b'a',b'x'*16],
              'dh':[b's'*32,self.p.dh_public(b'r'*32)]}[method]
        good[arg]=b'x'*size;self.reject('INVALID_INPUT',lambda:getattr(self.p,method)(*good))
    return test
for method,arg,expected in [('sign',0,32),('verify',0,32),('verify',2,64),('seal',0,32),('seal',1,24),('open',0,32),('open',1,24),('dh',0,32),('dh',1,32)]:
    for size in [0,expected-1,expected+1]:setattr(PrimitiveTests,f'test_{method}_arg{arg}_length_{size}',make_length(method,arg,size))

class ProviderPinTypeTests(CryptoTest):
    def test_boolean_schema_version_rejected(self):
        pin=json.loads(PIN.read_text());pin['schema_version']=True
        self.reject('PROVIDER_PIN',lambda:self.provider_module.SodiumProvider(pin,allow_legacy_experiment=True))
    def test_numeric_version_rejected(self):
        pin=json.loads(PIN.read_text());pin['version']=18
        self.reject('PROVIDER_PIN',lambda:self.provider_module.SodiumProvider(pin,allow_legacy_experiment=True))
    def test_all_candidate_paths_validated_before_loading(self):
        pin=json.loads(PIN.read_text());pin['candidate_paths'].append('relative.so')
        self.reject('PROVIDER_PATH',lambda:self.provider_module.SodiumProvider(pin,allow_legacy_experiment=True))
    def test_native_identity_agrees_with_harness(self):
        from harness.doctor import probe
        identity=probe(['sodium'],root=ROOT)['crypto_runtime'];self.assertTrue(identity['available'])
        self.assertEqual(identity['sha256'],self.p.identity['sha256']);self.assertEqual(identity['version'],self.p.identity['version'])
