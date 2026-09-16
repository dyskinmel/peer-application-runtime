"""Typed cryptographic objects, NOT the Space membership/control state machine.

`expected_*` and trusted package roots must come from authenticated application
state, never copied from the very untrusted object being accepted. Low-level
seal functions take reserved nonces; applications must use the durable writer.
"""
from __future__ import annotations
import re
from par_wire.codec import encode,decode
from par_wire.schema import default_schema
from par_wire.errors import WireError
from .errors import CryptoError
from .provider import fixed,bounded
from .primitives import domain,hashed,object_key
from .hpke import HPKE

APP=re.compile(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+')
def app_id(value):
    # Candidate intersection with Store's lower-case ID policy; no normalization.
    if type(value) is not str or len(value)>128 or not APP.fullmatch(value):raise CryptoError('OBJECT_SCHEMA')
    return value

def checked(rule,value):
    try:default_schema().validate(rule,value)
    except WireError:raise CryptoError('OBJECT_SCHEMA') from None
    return value

def parse(rule,raw,limit=786432):
    bounded(raw,limit,1)
    try:return checked(rule,decode(raw,max_bytes=limit))
    except WireError:raise CryptoError('OBJECT_SCHEMA') from None

def change_header(value):
    checked('change-header',value);app_id(value[0])
    if value[7]<1 or len(set(value[10]))!=len(value[10]):raise CryptoError('OBJECT_SCHEMA')
    return encode(value)

def _key(secret,h,block=False):return object_key(secret,h[0],h[1],h[2],h[4],h[3],h[6 if block else 15])
def envelope_id(raw):bounded(raw,786432,1);return hashed('envelope-id',[raw])
def block_id(raw):bounded(raw,270336,1);return hashed('block-id',[raw])
def package_id(raw):bounded(raw,65536,1);return hashed('key-package-id',[raw])
def certificate_id(raw):bounded(raw,65536,1);return hashed('certificate-id',[raw])

def _author(p,pk,h):
    fixed(pk,32)
    if h[5]!=hashed('device-id',[h[0],pk]):raise CryptoError('AUTHOR_MISMATCH')

def seal_change(p,epoch_secret,signing_seed,header,payload,nonce):
    hb=change_header(header);header=decode(hb);bounded(payload,524288);fixed(nonce,24)
    if header[11]!=len(payload):raise CryptoError('LENGTH_MISMATCH')
    _author(p,p.sign_public(signing_seed),header)
    ct=p.seal(_key(epoch_secret,header),nonce,domain('envelope-aad',[hb]),payload)
    sig=p.sign(signing_seed,domain('envelope-sign',[hb,nonce,ct]))
    return encode({0:hb,1:nonce,2:ct,3:sig})

def open_change(p,epoch_secret,signer_public,expected_header,raw):
    expected=change_header(expected_header);o=parse('change-envelope',raw)
    h=parse('change-header',o[0],16384);change_header(h)
    if o[0]!=expected:raise CryptoError('CONTEXT_MISMATCH')
    _author(p,signer_public,h)
    p.verify(signer_public,domain('envelope-sign',[o[0],o[1],o[2]]),o[3])
    if len(o[2])!=h[11]+16:raise CryptoError('LENGTH_MISMATCH')
    plain=p.open(_key(epoch_secret,h),o[1],domain('envelope-aad',[o[0]]),o[2])
    if len(plain)!=h[11]:raise CryptoError('LENGTH_MISMATCH')
    return plain

def block_header(h):checked('block-header',h);app_id(h[0]);return encode(h)
def seal_block(p,epoch_secret,header,payload,nonce):
    hb=block_header(header);header=decode(hb);bounded(payload,262144);fixed(nonce,24)
    if header[7]!=len(payload):raise CryptoError('LENGTH_MISMATCH')
    return encode({0:hb,1:nonce,2:p.seal(_key(epoch_secret,header,True),nonce,domain('block-aad',[hb]),payload)})
def open_block(p,epoch_secret,expected_header,raw):
    hb=block_header(expected_header);o=parse('sealed-block',raw,270336);h=parse('block-header',o[0],4096);block_header(h)
    if o[0]!=hb:raise CryptoError('CONTEXT_MISMATCH')
    plain=p.open(_key(epoch_secret,h,True),o[1],domain('block-aad',[o[0]]),o[2])
    if len(plain)!=h[7]:raise CryptoError('LENGTH_MISMATCH')
    return plain

def _signed(p,seed,label,body):
    raw=encode(body);bounded(raw,65536,1)
    return encode({0:raw,1:p.sign_public(seed),2:p.sign(seed,domain(label,[raw]))})
def _verify_signed(p,pk,label,rule,raw):
    fixed(pk,32);o=parse('signed-object',raw,66000)
    if o[1]!=pk:raise CryptoError('SIGNER_MISMATCH')
    p.verify(pk,domain(label,[o[0]]),o[2])
    return parse(rule,o[0],65536)

def create_certificate(p,account_seed,app,device_public,recipient_public,serial):
    app_id(app);pk=p.sign_public(account_seed)
    body={0:1,1:app,2:pk,3:device_public,4:recipient_public,5:serial};checked('certificate-body',body)
    if pk==device_public or pk==recipient_public or device_public==recipient_public:raise CryptoError('KEY_ROLE_REUSE')
    return _signed(p,account_seed,'certificate-sign',body)
def verify_certificate(p,app,expected_account_public,raw):
    app_id(app);body=_verify_signed(p,expected_account_public,'certificate-sign','certificate-body',raw)
    if body[1]!=app or body[2]!=expected_account_public:raise CryptoError('CONTEXT_MISMATCH')
    if len({body[2],body[3],body[4]})!=3:raise CryptoError('KEY_ROLE_REUSE')
    return body

def package_context(c):
    if type(c) is not dict or set(c)!=set(range(7)) or any(type(k) is not int for k in c):raise CryptoError('OBJECT_SCHEMA')
    checked('key-package-body',dict(c)|{7:1,8:b'0'*32,9:b'0'*16});app_id(c[0]);return decode(encode(c))

def _package_info(c):return domain('key-package-info',[c[0],c[1],c[2],c[3],c[5]])
def _package_aad(c):return domain('key-package-aad',[1,c[4],c[6]])
def _secret_body(secret,c):return {0:secret,1:c[0],2:c[1],3:c[2],4:c[3],5:c[4]}

def seal_package(p,authority_seed,recipient_public,context,epoch_secret,*,random_source=None):
    c=package_context(context);fixed(epoch_secret,32)
    enc,ct=HPKE(p).seal(recipient_public,_package_info(c),_package_aad(c),encode(_secret_body(epoch_secret,c)),random_source=random_source)
    body=dict(c)|{7:1,8:enc,9:ct};checked('key-package-body',body)
    return _signed(p,authority_seed,'key-package-sign',body)

def package_root(package_ids):
    if type(package_ids) is not list or not 1<=len(package_ids)<=1024:raise CryptoError('PACKAGE_ROOT_INVALID')
    if any(type(i) is not bytes or len(i)!=32 for i in package_ids) or len(set(package_ids))!=len(package_ids):raise CryptoError('PACKAGE_ROOT_INVALID')
    return hashed('package-root',[sorted(package_ids)])

def open_package(p,recipient_secret,authority_public,expected_context,raw,package_ids,trusted_package_root):
    c=package_context(expected_context);fixed(trusted_package_root,32)
    if package_root(package_ids)!=trusted_package_root or package_id(raw) not in package_ids:raise CryptoError('PACKAGE_ROOT_INVALID')
    body=_verify_signed(p,authority_public,'key-package-sign','key-package-body',raw)
    if any(body[k]!=v for k,v in c.items()):raise CryptoError('CONTEXT_MISMATCH')
    plain=HPKE(p).open(recipient_secret,body[8],_package_info(c),_package_aad(c),body[9])
    result=parse('epoch-secret-plaintext',plain,4096)
    if result!=_secret_body(result[0],c):raise CryptoError('CONTEXT_MISMATCH')
    return result[0]
