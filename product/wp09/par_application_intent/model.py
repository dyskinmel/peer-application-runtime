"""Bounded immutable application intent; metadata is NOT encrypted or authority."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,re
from product.wp04 import exchange as x
from product.wp09.par_secure_fetch.dependencies import targets_owned
from product.wp09.par_secure_fetch.persistence import require,FetchError

PROFILE='par-application-intent-local-0050'
MAX_BYTES=65536

def hex_string(value,n=64):
    return type(value)is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',value)is not None

def fixed(value,n):require(type(value)is bytes and len(value)==n,'INTENT_INPUT')

def check_binding(raw):
    try:
        v=x.unpack(raw,MAX_BYTES)
        require(type(v)is list and len(v)==4,'JOURNAL_BINDING')
        require(type(v[0])is list and len(v[0])==5,'JOURNAL_BINDING')
        x.scope_check(v[0]+[b'\0'*32]);fixed(v[1],16)
        require(hex_string(v[2],32),'JOURNAL_BINDING');fixed(v[3],32)
        require(x.pack(v,MAX_BYTES)==raw,'JOURNAL_BINDING')
    except Exception:raise FetchError('JOURNAL_BINDING')from None
    return raw

@dataclass(frozen=True,slots=True)
class ApplicationIntent:
    scope:tuple
    store_generation:bytes
    inbox_generation:str
    certificate_digest:bytes
    operation_id:bytes
    expected_revision:int
    targets:tuple
    authority_digest:bytes
    input_digest:bytes
    connection_generation:int

    def __post_init__(self):
        try:
            require(type(self.scope)in(tuple,list),'INTENT_INPUT')
            scope=tuple(self.scope);x.scope_check(list(scope))
            for value,n in [(self.store_generation,16),(self.certificate_digest,32),
                            (self.operation_id,16),(self.authority_digest,32),(self.input_digest,32)]:fixed(value,n)
            require(hex_string(self.inbox_generation,32),'INTENT_INPUT')
            require(type(self.expected_revision)is int and 0<=self.expected_revision<64,'INVALID_REVISION')
            require(type(self.connection_generation)is int and 0<=self.connection_generation<2**64,'INTENT_INPUT')
            object.__setattr__(self,'scope',scope)
            object.__setattr__(self,'targets',targets_owned(self.targets))
        except FetchError:raise
        except Exception:raise FetchError('INTENT_INPUT')from None

    def binding(self):
        return check_binding(x.pack([list(self.scope[:5]),self.store_generation,
                    self.inbox_generation,self.certificate_digest],MAX_BYTES))

    def to_bytes(self):
        return x.pack({0:1,1:PROFILE,2:list(self.scope),3:self.store_generation,
            4:self.inbox_generation,5:self.certificate_digest,6:self.operation_id,
            7:self.expected_revision,8:list(self.targets),9:self.authority_digest,
            10:self.input_digest,11:self.connection_generation},MAX_BYTES)

    @property
    def digest(self):return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls,raw):
        try:
            v=x.unpack(raw,MAX_BYTES);x.keys(v,range(12))
            require(type(v[0])is int and v[0]==1 and v[1]==PROFILE,'INTENT_ENCODING')
            result=cls(*(v[k]for k in range(2,12)))
            require(result.to_bytes()==raw,'INTENT_ENCODING');return result
        except FetchError:raise
        except Exception:raise FetchError('INTENT_ENCODING')from None

@dataclass(frozen=True,slots=True)
class JournalPin:
    metadata_digest:str
    sequence:int
    event_digest:str
    def __post_init__(self):
        require(hex_string(self.metadata_digest)and hex_string(self.event_digest),'JOURNAL_PIN')
        require(type(self.sequence)is int and 0<=self.sequence<=256,'JOURNAL_PIN')
        require(self.sequence!=0 or self.event_digest==self.metadata_digest,'JOURNAL_PIN')


def check_receipt(intent,row):
    """Structural binding only. Coordinator obtains rows from DocumentApplier."""
    keys={'profile','operationId','revision','heads','inputIds','eventDigest','candidatePersisted',
          'innerValidated','applied','replicated','phase','productQualified'}
    require(type(row)is dict and set(row)==keys,'RECEIPT_SCHEMA')
    require(row['profile']=='par-document-apply-local-0035' and
            row['operationId']==intent.operation_id.hex(),'RECEIPT_BINDING')
    require(type(row['revision'])is int and row['revision']==intent.expected_revision+1,'RECEIPT_BINDING')
    for name in ('heads','inputIds'):
        v=row[name]
        require(type(v)is list and 1<=len(v)<=128 and all(hex_string(h)for h in v)and len(set(v))==len(v),'RECEIPT_SCHEMA')
    require(set(t.hex()for t in intent.targets)<=set(row['inputIds']),'RECEIPT_BINDING')
    require(hex_string(row['eventDigest']),'RECEIPT_SCHEMA')
    for name in ('candidatePersisted','innerValidated','applied','replicated','productQualified'):
        require(type(row[name])is bool,'RECEIPT_SCHEMA')
    require(row['candidatePersisted']and not row['replicated']and not row['productQualified'],'RECEIPT_SCHEMA')
    require(row['applied']==row['innerValidated'] and row['phase']==
            ('CORE_VALIDATED_LOCAL_APPLY'if row['applied']else'CANDIDATE_ONLY'),'RECEIPT_SCHEMA')
