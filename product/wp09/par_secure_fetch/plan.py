"""Owned finite fetch intent, not authorization and not a success receipt."""
from dataclasses import dataclass
import hashlib,re
from product.wp04 import exchange as x
from product.wp09.par_secure_transport import PeerBinding
from .persistence import FetchError,require,save_new,load_pinned,MAX_METADATA

PROFILE='par-secure-fetch-local-0045'
@dataclass(frozen=True,slots=True)
class FetchPlan:
    scope: tuple
    snapshot: bytes
    descriptors: tuple
    binding: PeerBinding
    inbox_generation: str
    max_records: int=64
    max_bytes: int=8*1024*1024

    def __post_init__(self):
        try:
            require(type(self.scope)in(tuple,list));scope=tuple(self.scope);x.scope_check(list(scope))
            require(type(self.snapshot)is bytes and len(self.snapshot)==32)
            require(type(self.binding)is PeerBinding and self.binding.scope==scope,'PLAN_BINDING')
            require(type(self.inbox_generation)is str and re.fullmatch('[0-9a-f]{32}',self.inbox_generation)is not None)
            require(type(self.max_records)is int and 1<=self.max_records<=64)
            require(type(self.max_bytes)is int and 1<=self.max_bytes<=8388608)
            require(type(self.descriptors)in(tuple,list)and len(self.descriptors)<=self.max_records)
            rows=[]
            for row in self.descriptors:
                require(type(row)in(tuple,list));owned=tuple(row);x.descriptor_check(list(owned));rows.append(owned)
            require(len({r[0]for r in rows})==len(rows)and len({r[1]for r in rows})==len(rows),'DUPLICATE_DESCRIPTOR')
            require(sum(r[2]for r in rows)<=self.max_bytes,'PLAN_BYTE_BUDGET')
            object.__setattr__(self,'scope',scope);object.__setattr__(self,'descriptors',tuple(rows))
        except FetchError:raise
        except Exception:raise FetchError('INVALID_PLAN')from None

    def to_bytes(self):
        b=self.binding
        return x.pack({0:1,1:PROFILE,2:list(self.scope),3:self.snapshot,4:[list(d)for d in self.descriptors],
                       5:[b.peer_id,b.certificate,b.peer_sha256,b.generation],6:self.inbox_generation,
                       7:self.max_records,8:self.max_bytes},MAX_METADATA)
    @property
    def digest(self):return hashlib.sha256(self.to_bytes()).hexdigest()
    @classmethod
    def from_bytes(cls,raw):
        try:
            v=x.unpack(raw,MAX_METADATA);x.keys(v,range(9))
            require(type(v[0])is int and v[0]==1 and v[1]==PROFILE)
            require(type(v[5])is list and len(v[5])==4)
            b=PeerBinding(v[5][0],v[5][1],v[2],v[5][2],v[5][3])
            p=cls(v[2],v[3],v[4],b,v[6],v[7],v[8]);require(p.to_bytes()==raw)
            return p
        except FetchError:raise
        except Exception:raise FetchError('INVALID_PLAN')from None
    def save(self,path):return save_new(path,self.to_bytes())
    @classmethod
    def load(cls,path,*,expected_sha256):return cls.from_bytes(load_pinned(path,expected_sha256))
