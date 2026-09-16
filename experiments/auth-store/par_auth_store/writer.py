"""Prepare outside transaction, recheck bound authority inside payload commit."""
from par_crypto.store_writer import CryptoStoreWriter
from par_crypto.errors import CryptoError
from par_crypto import objects
from par_wire.codec import decode
from par_store.model import PreparedCommit
from .errors import AuthorityStoreError as E

class AuthenticatedWriter:
    def __init__(self,store,certificate,epoch_secret,signing_seed,local_secret,*,observer=None):
        self.store=store;self.certificate=certificate;self._busy=False
        self.crypto=CryptoStoreWriter(store._provider,store._storage,epoch_secret,signing_seed,local_secret,observer=observer)
    def _proof_exists(self,op):
        row=self.store._storage.connection.execute('SELECT proof_digest FROM auth_commits WHERE operation_id=?',(op,)).fetchone()
        if row is None:raise E('AUTH_STORE_CORRUPT')
        if not self.store.audit()['valid']:raise E('AUTH_STORE_CORRUPT')
    def read_committed(self,op,header,payload,cache):
        self.store._enter()
        if self._busy:raise E('REENTRANT_OPERATION')
        try:
            receipt=self.crypto.read_committed(op,header,payload,cache)
            if receipt is not None:self._proof_exists(op)
            return receipt
        except CryptoError as e:raise E(e.code) from None
    def prepare(self,op,header,payload,cache):
        self.store._enter(True)
        if self._busy:raise E('REENTRANT_OPERATION')
        self._busy=True
        try:
            h=decode(objects.change_header(header))
            row,permit,key_check=self.store._authorize(self.certificate,h,self.store._provider.sign_public(self.crypto.signing_seed),self.crypto.epoch_secret)
            prepared=self.crypto.prepare(op,h,payload,cache)
            if type(prepared) is not PreparedCommit:raise E('OPERATION_ALREADY_COMMITTED')
            return self.store._bind(prepared,row,permit,self.certificate,key_check)
        except CryptoError as e:raise E(e.code) from None
        finally:self._busy=False
    def write(self,op,header,payload,cache):
        self.store._enter(True)
        old=self.read_committed(op,header,payload,cache)
        # This is result recovery for a completed local operation, not new authority.
        if old is not None:return old
        return self.store.commit(self.prepare(op,header,payload,cache))
