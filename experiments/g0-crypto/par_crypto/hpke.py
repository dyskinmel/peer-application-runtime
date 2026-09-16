"""RFC 9180 base-mode single-shot candidate using existing native primitives.

No PSK/Auth/Export or reusable encryption context. This is NOT an audited HPKE
package. KATs and another code route do not replace cryptographic review.
"""
from __future__ import annotations
from .errors import CryptoError
from .provider import fixed,bounded
from .primitives import hkdf_extract,hkdf_expand,random_bytes

KEM=b'KEM\x00\x20'
SUITE=b'HPKE\x00\x20\x00\x01\x00\x03'

def _extract(suite,salt,label,ikm):return hkdf_extract(salt,b'HPKE-v1'+suite+label+ikm)
def _expand(suite,prk,label,info,size):return hkdf_expand(prk,size.to_bytes(2,'big')+b'HPKE-v1'+suite+label+info,size)

class HPKE:
    def __init__(self,provider,*,suite=(32,1,3)):
        if type(suite) is not tuple or suite!=(32,1,3) or any(type(x) is not int for x in suite):raise CryptoError('UNSUPPORTED_SUITE')
        self.p=provider
    def derive_keypair(self,ikm):
        bounded(ikm,1024,32)
        prk=_extract(KEM,b'',b'dkp_prk',ikm)
        sk=_expand(KEM,prk,b'sk',b'',32)
        return sk,self.p.dh_public(sk)
    def _shared(self,dh,context):
        return _expand(KEM,_extract(KEM,b'',b'eae_prk',dh),b'shared_secret',context,32)
    def _schedule(self,shared,info):
        fixed(shared,32);bounded(info,65536)
        context=b'\0'+_extract(SUITE,b'',b'psk_id_hash',b'')+_extract(SUITE,b'',b'info_hash',info)
        secret=_extract(SUITE,shared,b'secret',b'')
        return _expand(SUITE,secret,b'key',context,32),_expand(SUITE,secret,b'base_nonce',context,12)
    def seal(self,recipient_public,info,aad,plaintext,*,random_source=None):
        fixed(recipient_public,32);bounded(info,65536);bounded(aad,65536);bounded(plaintext,4080)
        sk,enc=self.derive_keypair(random_bytes(32,random_source))
        shared=self._shared(self.p.dh(sk,recipient_public),enc+recipient_public)
        key,nonce=self._schedule(shared,info)
        return enc,self.p.seal_ietf(key,nonce,aad,plaintext)
    def open(self,recipient_secret,enc,info,aad,ciphertext):
        fixed(recipient_secret,32);fixed(enc,32);bounded(info,65536);bounded(aad,65536);bounded(ciphertext,4096,16)
        recipient_public=self.p.dh_public(recipient_secret)
        shared=self._shared(self.p.dh(recipient_secret,enc),enc+recipient_public)
        key,nonce=self._schedule(shared,info)
        return self.p.open_ietf(key,nonce,aad,ciphertext)
