"""Pinned libsodium C ABI, no dynamic package loading or algorithm fallback.

The bundled pin describes the available experimental host, not a security
endorsement. Old images require explicit disposable-experiment consent. This
adapter deliberately never calls crypto_core_ed25519_is_valid_point.
"""
from __future__ import annotations
import ctypes as C
import hashlib
import re
from pathlib import Path
from .errors import CryptoError

MAX_INPUT=1_048_576
L=2**252+27742317777372353535851937790883648493

def fixed(value, size):
    if type(value) is not bytes or len(value)!=size:raise CryptoError('INVALID_INPUT')

def bounded(value, limit=MAX_INPUT, minimum=0):
    if type(value) is not bytes or not minimum<=len(value)<=limit:raise CryptoError('INVALID_INPUT')

def select_library(pin: dict) -> Path:
    if type(pin) is not dict or type(pin.get('schema_version')) is not int or pin.get('schema_version')!=1 or not re.fullmatch('[0-9a-f]{64}',str(pin.get('sha256',''))):
        raise CryptoError('PROVIDER_PIN')
    paths=pin.get('candidate_paths')
    if type(paths) is not list or not 1<=len(paths)<=8:raise CryptoError('PROVIDER_PIN')
    if any(type(v) is not str or '\0' in v or not Path(v).is_absolute() or '..' in Path(v).parts for v in paths):raise CryptoError('PROVIDER_PATH')
    selected=None
    for value in paths:
        if type(value) is not str:raise CryptoError('PROVIDER_PATH')
        p=Path(value)
        if not p.is_absolute() or '..' in p.parts:raise CryptoError('PROVIDER_PATH')
        if not p.is_file():continue
        p=p.resolve(strict=True)
        if not 0<p.stat().st_size<=64*1024*1024:raise CryptoError('PROVIDER_PATH')
        if hashlib.sha256(p.read_bytes()).hexdigest()==pin['sha256']:selected=p;break
    if selected is None:raise CryptoError('PROVIDER_PIN_MISMATCH')
    return selected

class SodiumProvider:
    def __init__(self, pin: dict, *, allow_legacy_experiment: bool=False):
        if type(allow_legacy_experiment) is not bool:raise CryptoError('INVALID_INPUT')
        path=select_library(pin)
        if type(pin.get('version')) is not str or not re.fullmatch(r'\d+\.\d+\.\d+',pin['version']):raise CryptoError('PROVIDER_PIN')
        try:
            parts=tuple(int(x) for x in pin['version'].split('.'))
            if len(parts)!=3:raise ValueError()
        except (KeyError,TypeError,ValueError):raise CryptoError('PROVIDER_PIN') from None
        if parts<(1,0,21) and not allow_legacy_experiment:raise CryptoError('PROVIDER_UPGRADE_REQUIRED')
        try:self._lib=C.CDLL(str(path))
        except OSError:raise CryptoError('PROVIDER_LOAD') from None
        def bind(name,args,ret=C.c_int):
            try:f=getattr(self._lib,name)
            except AttributeError:raise CryptoError('PROVIDER_ABI') from None
            f.argtypes=args;f.restype=ret;return f
        P=C.c_void_p;U=C.c_ulonglong
        self._init=bind('sodium_init',[])
        self._version=bind('sodium_version_string',[],C.c_char_p)
        self._wipe=bind('sodium_memzero',[P,C.c_size_t],None)
        self._keypair=bind('crypto_sign_seed_keypair',[P,P,P])
        self._sign=bind('crypto_sign_detached',[P,P,P,U,P])
        self._verify=bind('crypto_sign_verify_detached',[P,P,U,P])
        self._base=bind('crypto_scalarmult_curve25519_base',[P,P])
        self._dh=bind('crypto_scalarmult_curve25519',[P,P,P])
        self._aead={}
        for suffix in ('xchacha20poly1305_ietf','chacha20poly1305_ietf'):
            self._aead[suffix]=(bind('crypto_aead_'+suffix+'_encrypt',[P,P,P,U,P,U,P,P,P]),
                                 bind('crypto_aead_'+suffix+'_decrypt',[P,P,P,P,U,P,U,P,P]))
        if self._init()<0:raise CryptoError('PROVIDER_INIT')
        version=self._version().decode('ascii','strict')
        if version!=pin['version'] or hashlib.sha256(path.read_bytes()).hexdigest()!=pin['sha256']:
            raise CryptoError('PROVIDER_PIN_MISMATCH')
        self.identity={'provider':'libsodium-ctypes-local-candidate','provider_family':'libsodium','path':str(path),
            'sha256':pin['sha256'],'version':version,'security_qualified':False,
            'legacy_experiment':parts<(1,0,21),'auto_fallback':False,
            'maintenance_status':'LEGACY_VERSION_EXPERIMENT_ONLY' if parts<(1,0,21) else 'UNKNOWN',
            'key_protection':'PROCESS_MEMORY_UNVERIFIED',
            'capabilities':['sign_public','sign','verify','dh_public','dh','seal','open','seal_ietf','open_ietf'],
            'point_check':'S_CANONICAL_AND_CRYPTO_SIGN_VERIFY_DETACHED',
            'prime_subgroup_independent_validation':'NOT_ESTABLISHED',
            'dependency_closure':'TARGET_IMAGE_ONLY_NOT_COMPLETE_NATIVE_CLOSURE'}
    @staticmethod
    def _buf(data):return C.create_string_buffer(data,max(1,len(data)))
    def sign_public(self, seed: bytes) -> bytes:
        fixed(seed,32);pk=C.create_string_buffer(32);sk=C.create_string_buffer(64);sb=self._buf(seed)
        try:
            if self._keypair(pk,sk,sb)!=0:raise CryptoError('PROVIDER_FAILURE')
            return pk.raw
        finally:self._wipe(sk,64);self._wipe(sb,32)
    def sign(self,seed: bytes,message: bytes) -> bytes:
        fixed(seed,32);bounded(message)
        pk=C.create_string_buffer(32);sk=C.create_string_buffer(64);sb=self._buf(seed)
        sig=C.create_string_buffer(64);n=C.c_ulonglong();msg=self._buf(message)
        try:
            if self._keypair(pk,sk,sb)!=0 or self._sign(sig,C.byref(n),msg,len(message),sk)!=0 or n.value!=64:
                raise CryptoError('PROVIDER_FAILURE')
            return sig.raw
        finally:self._wipe(sk,64);self._wipe(sb,32);self._wipe(msg,max(1,len(message)))
    def verify(self,public_key: bytes,message: bytes,signature: bytes) -> None:
        fixed(public_key,32);fixed(signature,64);bounded(message)
        if int.from_bytes(signature[32:],'little')>=L:raise CryptoError('SIGNATURE_INVALID')
        if self._verify(self._buf(signature),self._buf(message),len(message),self._buf(public_key))!=0:
            raise CryptoError('SIGNATURE_INVALID')
    def dh_public(self,secret: bytes) -> bytes:
        fixed(secret,32);sb=self._buf(secret);out=C.create_string_buffer(32)
        try:
            if self._base(out,sb)!=0:raise CryptoError('KEM_INVALID')
            return out.raw
        finally:self._wipe(sb,32)
    def dh(self,secret: bytes,public_key: bytes) -> bytes:
        fixed(secret,32);fixed(public_key,32);sb=self._buf(secret);out=C.create_string_buffer(32)
        try:
            if self._dh(out,sb,self._buf(public_key))!=0:raise CryptoError('KEM_INVALID')
            return out.raw
        finally:self._wipe(sb,32);self._wipe(out,32)
    def _crypt(self,key,nonce,aad,data,*,decrypt,ietf):
        fixed(key,32);fixed(nonce,12 if ietf else 24);bounded(aad);bounded(data,MAX_INPUT,16 if decrypt else 0)
        out_size=len(data)-16 if decrypt else len(data)+16
        out=C.create_string_buffer(max(1,out_size));n=C.c_ulonglong();kb=self._buf(key);db=self._buf(data)
        suffix='chacha20poly1305_ietf' if ietf else 'xchacha20poly1305_ietf'
        try:
            if decrypt:code=self._aead[suffix][1](out,C.byref(n),None,db,len(data),self._buf(aad),len(aad),self._buf(nonce),kb)
            else:code=self._aead[suffix][0](out,C.byref(n),db,len(data),self._buf(aad),len(aad),None,self._buf(nonce),kb)
            if code!=0:raise CryptoError('AEAD_INVALID' if decrypt else 'PROVIDER_FAILURE')
            if n.value!=out_size:raise CryptoError('PROVIDER_FAILURE')
            return out.raw[:out_size]
        finally:
            self._wipe(kb,32);self._wipe(db,max(1,len(data)));self._wipe(out,max(1,out_size))
    def seal(self,key,nonce,aad,plaintext):return self._crypt(key,nonce,aad,plaintext,decrypt=False,ietf=False)
    def open(self,key,nonce,aad,ciphertext):return self._crypt(key,nonce,aad,ciphertext,decrypt=True,ietf=False)
    def seal_ietf(self,key,nonce,aad,plaintext):return self._crypt(key,nonce,aad,plaintext,decrypt=False,ietf=True)
    def open_ietf(self,key,nonce,aad,ciphertext):return self._crypt(key,nonce,aad,ciphertext,decrypt=True,ietf=True)
