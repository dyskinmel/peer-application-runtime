"""Opaque storage contracts; validating this model does NOT verify AEAD or signatures."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from par_wire.codec import encode
from .errors import StoreError

ENVELOPE_MAX=786432
CACHE_MAX=4194304
BLOCK_MAX=262144+4096
BLOCKS_MAX=128
SCHEMA_DIGEST=hashlib.sha256(b'PAR-local-store-candidate-00.05.00').digest()

def fixed(value: bytes, length: int):
    if type(value) is not bytes or len(value)!=length:raise StoreError('INVALID_INPUT')

def u64(value: int) -> bytes:
    if type(value) is not int or not 0<=value<2**64:raise StoreError('INVALID_INPUT')
    return value.to_bytes(8,'big')

def from_u64(value: bytes) -> int:
    fixed(value,8);return int.from_bytes(value,'big')

def bounded(value: bytes, size: int):
    if type(value) is not bytes or not 1<=len(value)<=size:raise StoreError('INVALID_INPUT')

def sha(data: bytes) -> bytes:return hashlib.sha256(data).digest()

def wal_reset_fixed(version: str) -> bool:
    try:v=tuple(int(x) for x in version.split('.'))
    except (TypeError,ValueError):return False
    return len(v)==3 and (v>=(3,51,3) or ((3,50,7)<=v<(3,51,0)) or ((3,44,6)<=v<(3,45,0)))

def require_sqlite(version: str, allow_unpatched: bool):
    if tuple(int(x) for x in version.split('.'))<(3,37,0):raise StoreError('SQLITE_TOO_OLD')
    if not wal_reset_fixed(version) and not allow_unpatched:raise StoreError('SQLITE_PATCH_REQUIRED')

@dataclass(frozen=True)
class PreparedCommit:
    operation_id: bytes
    input_digest: bytes
    space_id: bytes
    object_id: bytes
    actor_id: bytes
    actor_generation: bytes
    epoch: int
    sequence: int
    previous_envelope: bytes | None
    change_hash: bytes
    reservation_id: bytes
    envelope: bytes
    encrypted_cache: bytes
    encrypted_receipt: bytes
    dependencies: tuple[bytes,...] = ()
    blocks: tuple[bytes,...] = ()

    def validate(self):
        for v in (self.input_digest,self.space_id,self.object_id,self.actor_id,self.change_hash):fixed(v,32)
        for v in (self.operation_id,self.actor_generation,self.reservation_id):fixed(v,16)
        u64(self.epoch);u64(self.sequence)
        if self.sequence==0:raise StoreError('INVALID_INPUT')
        if self.previous_envelope is not None:fixed(self.previous_envelope,32)
        bounded(self.envelope,ENVELOPE_MAX);bounded(self.encrypted_cache,CACHE_MAX);bounded(self.encrypted_receipt,65536)
        if type(self.dependencies) is not tuple or len(self.dependencies)>128:raise StoreError('INVALID_INPUT')
        for d in self.dependencies:fixed(d,32)
        if len(set(self.dependencies))!=len(self.dependencies):raise StoreError('INVALID_INPUT')
        if type(self.blocks) is not tuple or len(self.blocks)>BLOCKS_MAX:raise StoreError('INVALID_INPUT')
        for b in self.blocks:bounded(b,BLOCK_MAX)
        if len(set(sha(b) for b in self.blocks))!=len(self.blocks):raise StoreError('INVALID_INPUT')

    @property
    def envelope_id(self) -> bytes:
        return sha(encode(['PAR',1,'envelope-id',[self.envelope]],max_bytes=1048576))

    @property
    def fingerprint(self) -> bytes:
        return sha(encode(['PAR-STORE-EXPERIMENT',1,[self.operation_id,self.input_digest,self.space_id,
            self.object_id,self.actor_id,self.actor_generation,self.epoch,self.sequence,self.previous_envelope,
            self.change_hash,self.reservation_id,sha(self.envelope),sha(self.encrypted_cache),sha(self.encrypted_receipt),
            sorted(self.dependencies),[sha(b) for b in self.blocks]]]))

@dataclass(frozen=True)
class CommitReceipt:
    operation_id: bytes
    input_digest: bytes
    envelope_id: bytes
    encrypted_receipt: bytes
    store_generation: bytes
    storage_class: str
