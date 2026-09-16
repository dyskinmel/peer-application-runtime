"""Ephemeral write binding; not a transferable capability or hardware fence."""
from dataclasses import dataclass, field
import hashlib
from par_wire.codec import encode,decode
from par_store.model import PreparedCommit
from par_crypto.primitives import hashed
from .errors import AuthorityStoreError as E

MAX_MATERIAL=900000
STATE_MAP={'CONTROL_REQUIRED':'control-pending','MEMBERSHIP_PENDING':'control-pending',
           'EPOCH_PENDING':'key-pending','ACTIVE':'ready','CONTROL_FORK':'fork','CONTROL_INVALID':'read-only'}
ROW_FIELDS=['space_id','app_id','replay','replay_digest','head','sequence','epoch','revision','phase','active_material']
def sha(b):return hashlib.sha256(b).digest()
def row_hash(row):
    # Frame fixed-size digest of bounded replay instead of allocating it twice.
    vals=[sha(row[k]) if k=='replay' else row[k] for k in ROW_FIELDS]
    return sha(encode(vals))
def proof_hash(values):return sha(encode(list(values)))
def pack_material(certificate,package,ids,manifest,seeds):
    try:return encode({0:certificate,1:package,2:list(ids),3:manifest,4:[[k,v] for k,v in sorted(seeds.items())]},max_bytes=MAX_MATERIAL)
    except Exception:raise E('AUTH_MATERIAL_LIMIT') from None

def unpack_material(raw):
    try:
        v=decode(raw,max_bytes=MAX_MATERIAL)
        if type(v) is not dict or set(v)!=set(range(5)) or type(v[4]) is not list:raise ValueError()
        pairs=v[4]
        if any(type(x) is not list or len(x)!=2 or type(x[0]) is not bytes for x in pairs):raise ValueError()
        seeds=dict(pairs)
        if len(seeds)!=len(pairs):raise ValueError()
        if pack_material(v[0],v[1],v[2],v[3],seeds)!=raw:raise ValueError()
        return v[0],v[1],v[2],v[3],seeds
    except Exception:raise E('AUTH_STORE_CORRUPT') from None

@dataclass(frozen=True)
class BoundWrite:
    prepared: PreparedCommit = field(repr=False)
    space_id: bytes
    head: bytes
    sequence: int
    epoch: int
    revision: int
    device_id: bytes
    certificate: bytes = field(repr=False)
    key_check: bytes = field(repr=False)
    material_id: bytes
    fence: bytes = field(repr=False)
    _owner: object = field(repr=False,compare=False)
    _seal: bytes = field(repr=False,compare=False)
    def sealed_bytes(self):
        return encode([self.prepared.fingerprint,self.space_id,self.head,self.sequence,self.epoch,self.revision,
                       self.device_id,sha(self.certificate),self.key_check,self.material_id,self.fence])
