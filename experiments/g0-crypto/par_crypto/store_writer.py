"""Experimental synchronous crypto/Store bridge with permanent nonce issuance.

No membership engine, secure key vault, durable nonce service across clones, or
physical power-loss guarantee. Read-only restored stores can decrypt receipts
but cannot be made writable through this adapter. Keys are caller supplied.
"""
from __future__ import annotations
import hashlib,hmac,sqlite3
from par_wire.codec import encode,decode
from par_wire.errors import WireError
from par_store.model import PreparedCommit,u64
from par_store.errors import StoreError
from par_store.store import sqlite_error
from .errors import CryptoError
from .provider import fixed,bounded
from .primitives import random_bytes,domain,hashed,hkdf_extract,hkdf_expand
from . import objects

class CryptoStoreWriter:
    def __init__(self,provider,store,epoch_secret,signing_seed,local_secret,*,random_source=None,observer=None):
        for key in (epoch_secret,signing_seed,local_secret):fixed(key,32)
        if len({epoch_secret,signing_seed,local_secret})!=3:raise CryptoError('KEY_ROLE_REUSE')
        self.p=provider;self.store=store;self.epoch_secret=epoch_secret;self.signing_seed=signing_seed;self.local_secret=local_secret
        self.random_source=random_source;self.observer=observer;self._active=False;self.fencing_token=store.fencing_token
    def _notify(self,stage):
        if self.observer:
            try:self.observer(stage)
            except Exception:raise CryptoError('CRYPTO_ABORTED') from None
    def _local_key(self,purpose):
        prk=hkdf_extract(hashed('crypto-local/salt',[self.store.generation]),self.local_secret)
        return hkdf_expand(prk,domain('crypto-local/key',[purpose]),32)
    def _input(self,op,header,payload,cache):
        fixed(op,16);hb=objects.change_header(header);bounded(payload,524288);bounded(cache,524288)
        if len(payload)!=header[11]:raise CryptoError('LENGTH_MISMATCH')
        objects._author(self.p,self.p.sign_public(self.signing_seed),header)
        # Hash framed request components before HMAC to retain bounded CBOR frames.
        request=domain('crypto-local/intent',[op,self.store.generation,hb,hashlib.sha256(payload).digest(),hashlib.sha256(cache).digest()])
        return hmac.digest(self._local_key('intent'),request,'sha256')
    def _reserve(self,op,intent,key):
        nonce=random_bytes(24,self.random_source)
        rid=self.store.reserve_nonce(op,intent,hashed('crypto-local/key-id',[key]),nonce)
        return rid,nonce
    def _local_aad(self,purpose,op,eid):return domain('crypto-local/record',[purpose,self.store.generation,op,eid])
    def _seal_local(self,purpose,op,intent,eid,plain):
        key=self._local_key(purpose);_,nonce=self._reserve(op,intent,key)
        return encode({0:1,1:nonce,2:self.p.seal(key,nonce,self._local_aad(purpose,op,eid),plain)})
    def _open_local(self,purpose,op,eid,raw):
        bounded(raw,600000,1)
        try:o=decode(raw,max_bytes=600000)
        except WireError:raise CryptoError('COMMITTED_DATA_INVALID') from None
        if type(o) is not dict or set(o)!={0,1,2} or any(type(k) is not int for k in o) or type(o[0]) is not int or o[0]!=1:raise CryptoError('COMMITTED_DATA_INVALID')
        fixed(o[1],24);bounded(o[2],524304,16)
        return self.p.open(self._local_key(purpose),o[1],self._local_aad(purpose,op,eid),o[2])
    def _receipt_plain(self,op,intent,eid,cache):
        return encode({0:op,1:intent,2:eid,3:self.store.generation,4:hashlib.sha256(cache).digest()})
    def _read(self,op,header,payload,cache,intent):
        old=self.store.lookup_operation(op,intent)
        if old is None:return None
        if old.store_generation!=self.store.generation:raise CryptoError('COMMITTED_DATA_INVALID')
        try:
            row=self.store.connection.execute('''SELECT e.encrypted_bytes,m.encrypted_cache FROM envelopes e
              JOIN commit_ledger l ON l.commit_id=e.envelope_id JOIN local_commit_meta m USING(operation_id)
              WHERE l.operation_id=?''',(op,)).fetchone()
        except sqlite3.Error as exc:raise sqlite_error(exc,op) from None
        if row is None or objects.envelope_id(row[0])!=old.envelope_id:raise CryptoError('COMMITTED_DATA_INVALID')
        plain=objects.open_change(self.p,self.epoch_secret,self.p.sign_public(self.signing_seed),header,row[0])
        if plain!=payload:raise CryptoError('COMMITTED_DATA_INVALID')
        if self._open_local('cache',op,old.envelope_id,row[1])!=cache:raise CryptoError('COMMITTED_DATA_INVALID')
        if self._open_local('receipt',op,old.envelope_id,old.encrypted_receipt)!=self._receipt_plain(op,intent,old.envelope_id,cache):raise CryptoError('COMMITTED_DATA_INVALID')
        return old
    def read_committed(self,op,header,payload,cache):
        if self._active:raise CryptoError('REENTRANT_OPERATION')
        self.store._alive()
        header=decode(objects.change_header(header))
        return self._read(op,header,payload,cache,self._input(op,header,payload,cache))
    def _check_context(self,h):
        try:row=self.store.connection.execute('SELECT app_id,state,content_epoch,control_head FROM spaces WHERE space_id=?',(h[1],)).fetchone()
        except sqlite3.Error as exc:raise sqlite_error(exc) from None
        if row is None or row[0]!=h[0] or row[1]!='ready' or row[2]!=u64(h[2]) or row[3]!=h[13]:raise CryptoError('STORE_CONTEXT_MISMATCH')
    def prepare(self,op,header,payload,cache):
        return self._write(op,header,payload,cache,commit=False)
    def commit(self,op,header,payload,cache):
        return self._write(op,header,payload,cache,commit=True)
    def _write(self,op,header,payload,cache,*,commit):
        if self._active:raise CryptoError('REENTRANT_OPERATION')
        self.store._writable()
        header=decode(objects.change_header(header))  # Own nested mutable input before callbacks/native calls.
        intent=self._input(op,header,payload,cache)
        self._active=True
        try:
            old=self._read(op,header,payload,cache,intent)
            if old is not None:return old
            self._check_context(header)
            key=objects._key(self.epoch_secret,header)
            rid,nonce=self._reserve(op,intent,key);self._notify('crypto.after_content_reservation')
            raw=objects.seal_change(self.p,self.epoch_secret,self.signing_seed,header,payload,nonce)
            self._notify('crypto.after_content_seal');eid=objects.envelope_id(raw)
            encrypted_cache=self._seal_local('cache',op,intent,eid,cache)
            encrypted_receipt=self._seal_local('receipt',op,intent,eid,self._receipt_plain(op,intent,eid,cache))
            actor=hashed('actor-id',[header[1],header[2],header[3],header[5],header[6]])
            prepared=PreparedCommit(op,intent,header[1],header[3],actor,header[6],header[2],header[7],header[8],header[12],rid,
                raw,encrypted_cache,encrypted_receipt,tuple(header[10]),())
            self._notify('crypto.before_store_commit')
            return self.store.commit(prepared,fencing_token=self.fencing_token) if commit else prepared
        finally:self._active=False
