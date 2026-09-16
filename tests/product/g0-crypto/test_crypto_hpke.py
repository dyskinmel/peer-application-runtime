from crypto_support import CryptoTest,fixture
class HPKETests(CryptoTest):
    def setUp(self):
        super().setUp();self.h=self.require('hpke').HPKE(self.p);self.v=fixture('hpke-base.json');self.b=lambda k:bytes.fromhex(self.v[k])
    def test_derive_keypair_rfc(self):
        self.assertEqual(self.h.derive_keypair(self.b('ikmE')),(self.b('skEm'),self.b('pkEm')))
        self.assertEqual(self.h.derive_keypair(self.b('ikmR')),(self.b('skRm'),self.b('pkRm')))
    def test_rfc9180_single_shot_known_answer(self):
        enc,ct=self.h.seal(self.b('pkRm'),self.b('info'),self.b('aad'),self.b('pt'),random_source=lambda n:self.b('ikmE'))
        self.assertEqual(enc,self.b('pkEm'));self.assertEqual(ct,self.b('ct'))
        self.assertEqual(self.h.open(self.b('skRm'),enc,self.b('info'),self.b('aad'),ct),self.b('pt'))
    def test_intermediate_rfc_schedule(self):
        shared=self.h._shared(self.p.dh(self.b('skEm'),self.b('pkRm')),self.b('pkEm')+self.b('pkRm'))
        self.assertEqual(shared,self.b('shared_secret'));self.assertEqual(self.h._schedule(shared,self.b('info')),(self.b('key'),self.b('base_nonce')))
    def test_ephemeral_is_fresh(self):
        a=self.h.seal(self.b('pkRm'),b'i',b'a',b'p');b=self.h.seal(self.b('pkRm'),b'i',b'a',b'p');self.assertNotEqual(a[0],b[0])
    def test_random_failure_no_result(self):
        def broken(n):raise OSError('rng')
        self.reject('RNG_FAILURE',lambda:self.h.seal(self.b('pkRm'),b'i',b'a',b'p',random_source=broken))
    def test_unsupported_suite(self):
        self.reject('UNSUPPORTED_SUITE',lambda:self.require('hpke').HPKE(self.p,suite=(32,1,1)))
    def test_no_empty_ciphertext(self):self.reject('INVALID_INPUT',lambda:self.h.open(self.b('skRm'),self.b('pkEm'),b'i',b'a',b''))
    def test_low_order_recipient(self):self.reject('KEM_INVALID',lambda:self.h.seal(b'\0'*32,b'i',b'a',b'p'))
    def test_low_order_enc(self):self.reject('KEM_INVALID',lambda:self.h.open(self.b('skRm'),b'\0'*32,b'i',b'a',b'x'*16))
    def test_info_bound(self):self.reject('AEAD_INVALID',lambda:self.h.open(self.b('skRm'),self.b('pkEm'),b'wrong',self.b('aad'),self.b('ct')))
    def test_aad_bound(self):self.reject('AEAD_INVALID',lambda:self.h.open(self.b('skRm'),self.b('pkEm'),self.b('info'),b'wrong',self.b('ct')))
    def test_wrong_recipient_secret(self):self.reject('AEAD_INVALID',lambda:self.h.open(b'x'*32,self.b('pkEm'),self.b('info'),self.b('aad'),self.b('ct')))
    def test_ciphertext_bitflip(self):
        c=self.b('ct');self.reject('AEAD_INVALID',lambda:self.h.open(self.b('skRm'),self.b('pkEm'),self.b('info'),self.b('aad'),c[:-1]+bytes([c[-1]^1])))
