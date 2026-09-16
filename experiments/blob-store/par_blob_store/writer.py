"""Verify sealed attachments; bind retry input before any document nonce issuance.

This API takes encrypted chunks, not plaintext file paths. It does not validate
Automerge semantics or prove completeness of a whole multi-chunk file.
"""
from dataclasses import replace
import hmac
from par_auth_store.writer import AuthenticatedWriter
from par_crypto.store_writer import CryptoStoreWriter
from par_crypto import objects
from par_crypto.primitives import domain
from par_wire.codec import encode,decode
from par_store.model import PreparedCommit
from .model import inspect_batch, sha, sign_manifest
from .errors import BlobStoreError as E

class AttachmentCryptoWriter(CryptoStoreWriter):
    def __init__(self,*args,bindings=(),**kw):
        super().__init__(*args,**kw)
        self._attachment_digest=sha(encode([b.descriptor() for b in bindings]))
    def _input(self,op,header,payload,cache):
        base=super()._input(op,header,payload,cache)
        return hmac.digest(self._local_key('blob-intent'),domain('blob-store-local/intent',[base,self._attachment_digest]),'sha256')

class BlobWriter(AuthenticatedWriter):
    def _request(self,header,attachments):
        h=decode(objects.change_header(header))
        bindings=inspect_batch(attachments,h,self.store._provider,self.crypto.epoch_secret)
        c=AttachmentCryptoWriter(self.store._provider,self.store._storage,self.crypto.epoch_secret,
                                self.crypto.signing_seed,self.crypto.local_secret,
                                bindings=bindings,observer=self.crypto.observer)
        return h,bindings,c
    def read_committed(self,op,header,payload,cache,*,attachments=()):
        self.store._enter()
        if self._busy:raise E('REENTRANT_OPERATION')
        h,bindings,crypto=self._request(header,attachments)
        receipt=crypto.read_committed(op,h,payload,cache)
        if receipt is not None:
            self._proof_exists(op)
            stored=self.store.attachments(receipt.envelope_id)
            if tuple(x.descriptor() for x in stored)!=tuple(x.descriptor() for x in bindings):raise E('ATTACHMENT_MANIFEST')
        return receipt
    def prepare(self,op,header,payload,cache,*,attachments=()):
        self.store._enter(True)
        if self._busy:raise E('REENTRANT_OPERATION')
        self._busy=True
        try:
            h,bindings,crypto=self._request(header,attachments)
            row,permit,key_check=self.store._authorize(self.certificate,h,self.store._provider.sign_public(crypto.signing_seed),crypto.epoch_secret)
            prepared=crypto.prepare(op,h,payload,cache)
            if type(prepared) is not PreparedCommit:raise E('OPERATION_ALREADY_COMMITTED')
            prepared=replace(prepared,blocks=tuple(a.sealed_bytes for a in attachments))
            prepared.validate()
            bound=self.store._bind(prepared,row,permit,self.certificate,key_check)
            manifest=sign_manifest(self.store._provider,crypto.signing_seed,prepared,bindings)
            return self.store._bind_blob(bound,manifest)
        finally:self._busy=False
    def write(self,op,header,payload,cache,*,attachments=()):
        self.store._enter(True)
        old=self.read_committed(op,header,payload,cache,attachments=attachments)
        if old is not None:return old
        return self.store.commit(self.prepare(op,header,payload,cache,attachments=attachments))
