"""Bounded HKDF over stdlib HMAC; typed domain inputs use existing strict CBOR."""
from __future__ import annotations
import hashlib,hmac,os,re
from par_wire.codec import encode
from par_wire.errors import WireError
from .provider import bounded,fixed
from .errors import CryptoError

def random_bytes(size: int, source=None) -> bytes:
    if type(size) is not int or not 1<=size<=1024:raise CryptoError('INVALID_INPUT')
    try:value=(os.urandom if source is None else source)(size)
    except Exception:raise CryptoError('RNG_FAILURE') from None
    if type(value) is not bytes or len(value)!=size:raise CryptoError('RNG_FAILURE')
    return value

def hkdf_extract(salt: bytes,ikm: bytes) -> bytes:
    bounded(salt);bounded(ikm)
    return hmac.digest(salt or b'\0'*32,ikm,'sha256')

def hkdf_expand(prk: bytes,info: bytes,length: int) -> bytes:
    fixed(prk,32);bounded(info)
    if type(length) is not int or not 0<=length<=255*32:raise CryptoError('INVALID_INPUT')
    last=b'';out=bytearray()
    for i in range(1,(length+31)//32+1):
        last=hmac.digest(prk,last+info+bytes([i]),'sha256');out.extend(last)
    return bytes(out[:length])

def domain(label: str,parts: list) -> bytes:
    if type(label) is not str or not re.fullmatch('[a-z][a-z0-9/-]{0,63}',label) or type(parts) is not list:
        raise CryptoError('INVALID_INPUT')
    try:return encode(['PAR',1,label,parts])
    except WireError:raise CryptoError('INVALID_INPUT') from None

def hashed(label: str,parts: list) -> bytes:return hashlib.sha256(domain(label,parts)).digest()

def object_key(epoch_secret,app_id,space_id,epoch,kind,object_id,key_generation):
    fixed(epoch_secret,32);fixed(space_id,32);fixed(object_id,32)
    if type(app_id) is not str or not re.fullmatch('[a-z0-9][a-z0-9.-]{0,127}',app_id):raise CryptoError('INVALID_INPUT')
    for v in (epoch,key_generation):
        if type(v) is not int or not 0<=v<2**64:raise CryptoError('INVALID_INPUT')
    if type(kind) is not int or not 1<=kind<=7:raise CryptoError('INVALID_INPUT')
    prk=hkdf_extract(hashed('epoch-salt',[app_id,space_id,epoch]),epoch_secret)
    return hkdf_expand(prk,domain('object-key',[kind,object_id,key_generation]),32)
