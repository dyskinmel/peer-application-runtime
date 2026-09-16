"""Bounded canonical parsing and explicit translation of dependency errors."""
from par_wire.codec import encode,decode
from par_wire.schema import default_schema
from par_wire.errors import WireError
from par_crypto.errors import CryptoError
from par_crypto import objects
from .errors import AuthError

def fixed(value,length):
    if type(value) is not bytes or len(value)!=length:raise AuthError('SCHEMA_INVALID')
def blob(value,maximum,minimum=1):
    if type(value) is not bytes or not minimum<=len(value)<=maximum:raise AuthError('SCHEMA_INVALID')
def schema(rule,value):
    try:default_schema().validate(rule,value)
    except WireError:raise AuthError('SCHEMA_INVALID') from None
    return value
def parse(rule,raw,limit=66000):
    blob(raw,limit)
    try:v=decode(raw,max_bytes=limit)
    except WireError:raise AuthError('SCHEMA_INVALID') from None
    return schema(rule,v)
def app(value):
    try:objects.app_id(value)
    except CryptoError:raise AuthError('SCHEMA_INVALID') from None
    return value
def canonical(value,limit=1048576):
    try:return encode(value,max_bytes=limit)
    except WireError:raise AuthError('RESOURCE_BLOCKED') from None

def crypto(call,*args,**kwargs):
    try:return call(*args,**kwargs)
    except CryptoError:raise AuthError('CRYPTO_INVALID') from None
