"""Different code route/native provider, same author: NOT independent review."""
import hashlib,json,subprocess,shutil
from crypto_support import CryptoTest,ROOT,fixture
from par_crypto.hpke import HPKE
from par_crypto.primitives import domain,hkdf_extract,hkdf_expand
class InteropTests(CryptoTest):
    def setUp(self):
        super().setUp();self.script=ROOT/'experiments/g0-crypto/node_oracle.mjs'
        self.assertTrue(self.script.is_file(),'Node/OpenSSL oracle not implemented')
        self.node=shutil.which('node');self.assertIsNotNone(self.node,'Node is required, never SKIP')
    def call(self,requests):
        p=subprocess.run([self.node,str(self.script)],input=json.dumps(requests),text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);out=json.loads(p.stdout);self.assertEqual(len(out),len(requests));return out
    def test_provider_identity(self):
        info=self.call([{'op':'identity'}])[0];self.assertIn('openssl',info);self.assertIn('node',info);self.assertFalse(info['independent_review'])
    def test_rfc_hpke_node_expected_ciphertext(self):
        f=fixture('hpke-base.json');r=self.call([dict(f,op='hpke-seal')])[0]
        self.assertEqual(r['enc'],f['pkEm']);self.assertEqual(r['ct'],f['ct'])
    def test_rfc_hpke_node_open(self):
        f=fixture('hpke-base.json');r=self.call([dict(f,op='hpke-open',enc=f['pkEm'])])[0];self.assertEqual(r['pt'],f['pt'])
    def test_generated_hpke_64_cases_both_directions(self):
        hpke=HPKE(self.p);requests=[];expected=[]
        for i in range(64):
            ikm=hashlib.sha256(b'public-ephemeral-'+bytes([i])).digest();sk=hashlib.sha256(b'public-recipient-'+bytes([i])).digest()
            pub=self.p.dh_public(sk);info=b'context'+bytes([i]);aad=b'aad'+bytes([i]);pt=(b'public fixture'+bytes([i]))*i
            enc,ct=hpke.seal(pub,info,aad,pt,random_source=lambda n,k=ikm:k)
            requests.append({'op':'hpke-seal','ikmE':ikm.hex(),'pkRm':pub.hex(),'info':info.hex(),'aad':aad.hex(),'pt':pt.hex()})
            requests.append({'op':'hpke-open','skRm':sk.hex(),'enc':enc.hex(),'info':info.hex(),'aad':aad.hex(),'ct':ct.hex()})
            expected.append((sk,info,aad,pt,enc,ct))
        results=self.call(requests)
        for i,(sk,info,aad,pt,enc,ct) in enumerate(expected):
            with self.subTest(case=i):
                a,b=results[2*i:2*i+2];self.assertEqual(a,{'enc':enc.hex(),'ct':ct.hex()});self.assertEqual(b,{'pt':pt.hex()})
                self.assertEqual(hpke.open(sk,bytes.fromhex(a['enc']),info,aad,bytes.fromhex(a['ct'])),pt)
    def test_generated_ed25519_64_domain_signatures(self):
        requests=[];expected=[]
        for i in range(64):
            seed=hashlib.sha256(b'public-signing-'+bytes([i])).digest();msg=domain('envelope-sign',[bytes([i])*i,b'n'*24,b'C'*i])
            pk=self.p.sign_public(seed);sig=self.p.sign(seed,msg);expected.append((pk,msg,sig))
            requests.extend([{'op':'ed-sign','seed':seed.hex(),'message':msg.hex()},{'op':'ed-verify','pk':pk.hex(),'message':msg.hex(),'signature':sig.hex()}])
        results=self.call(requests)
        for i,(pk,msg,sig) in enumerate(expected):
            with self.subTest(case=i):
                a,b=results[2*i:2*i+2];self.assertEqual(a,{'pk':pk.hex(),'signature':sig.hex()});self.assertEqual(b,{'valid':True})
                self.p.verify(pk,msg,bytes.fromhex(a['signature']))
    def test_hpke_modified_ciphertexts_rejected(self):
        f=fixture('hpke-base.json');ct=bytes.fromhex(f['ct']);requests=[]
        for i in range(len(ct)):
            changed=bytearray(ct);changed[i]^=1
            requests.append(dict(f,op='hpke-open',enc=f['pkEm'],ct=bytes(changed).hex()))
        for out in self.call(requests):self.assertEqual(out,{'error':'REJECTED'})
    def test_ed25519_invalid_cases_rejected(self):
        seed=b'K'*32;msg=b'public fixture';pk=self.p.sign_public(seed);sig=self.p.sign(seed,msg)
        requests=[{'op':'ed-verify','pk':pk.hex(),'message':(msg+b'!').hex(),'signature':sig.hex()},
            {'op':'ed-verify','pk':pk.hex(),'message':msg.hex(),'signature':(sig[:32]+b'\xff'*32).hex()},
            {'op':'ed-verify','pk':(b'\0'*32).hex(),'message':msg.hex(),'signature':(b'\0'*64).hex()}]
        for out in self.call(requests):self.assertEqual(out,{'valid':False})
    def test_hkdf_native_comparison(self):
        req=[];expected=[]
        for n in (1,31,32,33,65,256,8160):
            ikm=b'i'*32;salt=b's'*32;info=b'info';expected.append(hkdf_expand(hkdf_extract(salt,ikm),info,n).hex())
            req.append({'op':'hkdf','ikm':ikm.hex(),'salt':salt.hex(),'info':info.hex(),'length':n})
        self.assertEqual([x['okm'] for x in self.call(req)],expected)
    def test_oracle_unknown_operation_rejected(self):self.assertEqual(self.call([{'op':'shell'}]),[{'error':'REJECTED'}])
    def test_oracle_malformed_hex_rejected(self):self.assertEqual(self.call([{'op':'ed-sign','seed':'x'*64,'message':''}]),[{'error':'REJECTED'}])
