"""Single-change admission contracts. This module is NOT a CRDT implementation.

Decoded reports come only from an owner-selected, byte-pinned engine. JSON alone
is never cryptographic proof. Contract-test reports must be explicitly enabled
and cannot assert semantic validation. All public byte inputs are copied/bounded.
"""
from __future__ import annotations
import base64, hashlib, json
from dataclasses import dataclass, field
from par_wire.codec import encode, decode
from par_crypto import objects
from par_crypto.primitives import hashed

PROFILE = 'par-shared-change-local-0032'
MAX_CHANGE = 524288
MAX_CLOSURE = 128
MAX_CLOSURE_BYTES = 4 * 1024 * 1024
MAX_TEXT = 1024 * 1024
MAX_SAFE_INTEGER = 2**53 - 1

class SharedChangeError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def require(condition, code='INVALID_INPUT'):
    if not condition: raise SharedChangeError(code)

def canonical(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError): raise SharedChangeError('INVALID_INPUT') from None

def request_digest(value) -> str: return hashlib.sha256(canonical(value)).hexdigest()
def hex32(v): return type(v) is str and len(v)==64 and all(c in '0123456789abcdef' for c in v)
def ids(v,limit=MAX_CLOSURE): return type(v) is list and len(v)<=limit and all(hex32(x) for x in v) and len(set(v))==len(v)
def text(v,limit):
    require(type(v) is str)
    try: require(len(v.encode('utf-8'))<=limit, 'RESOURCE_LIMIT')
    except UnicodeError: raise SharedChangeError('INVALID_INPUT') from None

@dataclass(frozen=True)
class ChangeInput:
    header_bytes: bytes = field(repr=False)
    payload: bytes = field(repr=False)
    actor: bytes
    @property
    def header(self): return decode(self.header_bytes)
    @classmethod
    def create(cls, header, payload, *, schema_id):
        require(type(payload) is bytes and 0<len(payload)<=MAX_CHANGE)
        require(type(schema_id) is bytes and len(schema_id)==32)
        try: hb=objects.change_header(header); h=decode(hb)
        except Exception: raise SharedChangeError('INVALID_HEADER') from None
        for i in (2,4,7,11,14,15): require(type(h[i]) is int,'INVALID_HEADER')
        require(h[4]==1,'UNSUPPORTED_KIND')
        require(h[14]==1,'UNSUPPORTED_CODEC')
        require(h[7]<=MAX_SAFE_INTEGER,'UNSUPPORTED_INTEGER_RANGE')
        require(h[9]==schema_id,'SCHEMA_MISMATCH')
        require(h[11]==len(payload),'LENGTH_MISMATCH')
        require(h[12] not in h[10],'SELF_DEPENDENCY')
        require((h[7]==1 and h[8] is None) or (h[7]>1 and h[8] is not None),'PREVIOUS_MISMATCH')
        actor=hashed('actor-id',[h[i] for i in (1,2,3,5,6)])
        return cls(hb,bytes(payload),actor)
    def descriptor(self):
        h=self.header
        return {'actor':self.actor.hex(),'sequence':str(h[7]),'hash':h[12].hex(),
                'dependencies':sorted(x.hex() for x in h[10]),'change':base64.b64encode(self.payload).decode('ascii')}

@dataclass(frozen=True)
class Dependency:
    envelope_id: bytes
    change: ChangeInput

def core_request(candidate: ChangeInput, closure: tuple[Dependency,...]) -> dict:
    require(type(candidate) is ChangeInput and type(closure) is tuple)
    require(len(closure)<=MAX_CLOSURE,'RESOURCE_LIMIT')
    h=candidate.header; nodes={}; by_envelope={}; total=len(candidate.payload)
    for dep in closure:
        require(type(dep) is Dependency and type(dep.envelope_id) is bytes and len(dep.envelope_id)==32)
        d=dep.change.header
        require(all(d[i]==h[i] for i in (0,1,2,3,4,9,14,15)),'DEPENDENCY_SCOPE_MISMATCH')
        require(d[12] not in nodes and dep.envelope_id not in by_envelope,'DEPENDENCY_EQUIVOCATION')
        nodes[d[12]]=dep;by_envelope[dep.envelope_id]=dep;total+=len(dep.change.payload)
    require(total<=MAX_CLOSURE_BYTES,'RESOURCE_LIMIT')
    seen=set();visiting=set();ordered=[]
    def visit(cid):
        require(cid in nodes,'DEPENDENCIES_MISSING')
        require(cid not in visiting,'DEPENDENCY_CYCLE')
        if cid in seen:return
        visiting.add(cid);d=nodes[cid]
        for parent in sorted(d.change.header[10]):visit(parent)
        visiting.remove(cid);seen.add(cid);ordered.append(d)
    for cid in sorted(h[10]):visit(cid)
    require(seen==set(nodes),'EXTRANEOUS_DEPENDENCY')
    require(h[12] not in nodes,'CHANGE_ALREADY_PRESENT')
    # Prior author link must be present in the exact causal closure, not just DB.
    for current in [d.change for d in ordered]+[candidate]:
        c=current.header
        if c[7]==1:continue
        require(c[8] in by_envelope,'PREVIOUS_MISMATCH')
        p=by_envelope[c[8]].change
        require(p.actor==current.actor and p.header[7]==c[7]-1,'PREVIOUS_MISMATCH')
        reachable=set();todo=list(c[10])
        while todo:
            x=todo.pop()
            if x in reachable:continue
            require(x in nodes,'DEPENDENCIES_MISSING');reachable.add(x);todo+=nodes[x].change.header[10]
        require(p.header[12] in reachable,'PREVIOUS_MISMATCH')
    slots={}
    for d in [x.change for x in ordered]+[candidate]:
        slot=(d.actor,d.header[7]);cid=d.header[12]
        require(slot not in slots or slots[slot]==cid,'ACTOR_EQUIVOCATION');slots[slot]=cid
    return {'profile':PROFILE,'schema':'note-v1-local','candidate':candidate.descriptor(),
            'closure':[d.change.descriptor() for d in ordered]}

@dataclass(frozen=True)
class CheckedReport:
    request_hash: str
    engine_json: bytes = field(repr=False)
    note_json: bytes = field(repr=False)
    semantic_validated: bool
    @property
    def note(self):return json.loads(self.note_json)
    @property
    def engine(self):return json.loads(self.engine_json)


def check_report(request, report, *, expected_engine, allow_contract_double=False):
    require(type(allow_contract_double) is bool)
    require(type(report) is dict and set(report)=={'profile','requestDigest','engine','changes','appliedHashes','missing','note','schema'},'CORE_REPORT_INVALID')
    require(report['profile']==PROFILE and report['schema']=='note-v1-local' and report['requestDigest']==request_digest(request),'CORE_CONTEXT_MISMATCH')
    e=report['engine']
    require(type(e) is dict and set(e)=={'name','version','kind','digest'} and hex32(e.get('digest')),'CORE_REPORT_INVALID')
    require(e==expected_engine,'CORE_IDENTITY_CHANGED')
    require(e['name']=='@automerge/automerge' and e['version']=='3.4.1','CORE_IDENTITY_CHANGED')
    require(e['kind']=='automerge' or (allow_contract_double and e['kind']=='contract-test-double'),'CORE_NOT_REAL')
    require(type(report['missing']) is list and ids(report['missing']),'CORE_REPORT_INVALID')
    require(not report['missing'],'DEPENDENCIES_MISSING')
    changes=report['changes'];require(type(changes) is list and len(changes)==1,'NOT_SINGLE_CHANGE')
    c=changes[0];require(type(c) is dict and set(c)=={'actor','sequence','hash','dependencies'},'CORE_REPORT_INVALID')
    expected={k:request['candidate'][k] for k in ('actor','sequence','hash','dependencies')}
    require(ids(c.get('dependencies')) and type(c.get('sequence')) is str,'CORE_REPORT_INVALID')
    require(dict(c,dependencies=sorted(c['dependencies']))==expected,'INNER_OUTER_MISMATCH')
    applied=report['appliedHashes'];require(ids(applied,MAX_CLOSURE+1),'APPLIED_SET_MISMATCH')
    require(set(applied)=={x['hash'] for x in request['closure']}|{expected['hash']},'APPLIED_SET_MISMATCH')
    note=report['note'];require(type(note) is dict and set(note)=={'title','body','titleConflicts'},'CORE_REPORT_INVALID')
    text(note['title'],1024);text(note['body'],MAX_TEXT)
    values=note['titleConflicts'];require(type(values) is list and len(values)<=32,'RESOURCE_LIMIT')
    for v in values:text(v,1024)
    return CheckedReport(request_digest(request),canonical(e),canonical(note),e['kind']=='automerge')
