"""Bounded metadata-only inventory. This is not a deletion authorization format."""
from __future__ import annotations
import copy
import hashlib
import json
import re

PROFILE = 'management-record-lifecycle-local-v1'
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 512
MAX_ANCHORS = 1024
MAX_STORAGE = 128 * 1024 * 1024
GATES = ('jobs', 'control', 'submissions', 'archive_resolver')
STATES = {
    'job': {'QUEUED', 'VALIDATED', 'PREPARED', 'EXECUTING', 'OUTCOME_UNKNOWN', 'RETRY_READY', 'SUCCEEDED', 'CANCELLED'},
    'control': {'INFLIGHT', 'ACCEPTED', 'OUTCOME_UNKNOWN'},
    'submission': {'RECEIVING', 'READY', 'INFLIGHT', 'RETRY_READY', 'REGISTERED', 'INTENT', 'PAYLOAD_REMOVED', 'TOMBSTONED'},
}
TERMINAL = {'job': {'SUCCEEDED', 'CANCELLED'}, 'control': {'ACCEPTED'}, 'submission': {'TOMBSTONED'}}

class LifecycleError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def require(ok: bool, code: str = 'SCHEMA') -> None:
    if not ok:
        raise LifecycleError(code)

def integer(v, lo=0, hi=2**53-1):
    require(type(v) is int and lo <= v <= hi)

def hex32(v):
    require(type(v) is str and re.fullmatch('[a-f0-9]{64}', v) is not None)

def keys(v, names):
    require(type(v) is dict and all(type(k) is str for k in v) and set(v) == set(names))

def sha(raw: bytes) -> str:
    require(type(raw) is bytes)
    return hashlib.sha256(raw).hexdigest()

def canonical(v) -> bytes:
    try:
        raw = json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    except (ValueError, TypeError, RecursionError):
        raise LifecycleError('SCHEMA') from None
    require(len(raw) <= MAX_BYTES, 'CAPACITY')
    return raw

def decode(raw: bytes):
    require(type(raw) is bytes)
    require(len(raw) <= MAX_BYTES, 'CAPACITY')
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out)
            out[k] = v
        return out
    def constant(_):
        raise LifecycleError('SCHEMA')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise LifecycleError('SCHEMA') from None

def ref_key(v):
    require(type(v) is str and re.fullmatch('(job|control|submission|evidence|policy):[a-f0-9]{64}', v) is not None)

def validate_record(r):
    keys(r, ('key','kind','local_id','state','intent_digest','input_digest','proof_digest','refs','evidence_digest','storage_bytes','reserved_bytes'))
    require(type(r['kind']) is str and r['kind'] in STATES)
    for k in ('local_id', 'intent_digest', 'input_digest', 'proof_digest'):
        hex32(r[k])
    require(r['key'] == r['kind'] + ':' + r['local_id'])
    require(type(r['state']) is str and r['state'] in STATES[r['kind']])
    integer(r['storage_bytes'], 0, MAX_STORAGE)
    integer(r['reserved_bytes'], 0, MAX_STORAGE)
    if r['evidence_digest'] is not None:
        hex32(r['evidence_digest'])
    if r['kind'] == 'job':
        require((r['evidence_digest'] is not None) == (r['state'] == 'SUCCEEDED'))
    if r['kind'] == 'control':
        require(r['evidence_digest'] is None)
    require(type(r['refs']) is list and len(r['refs']) <= 16)
    for ref in r['refs']:
        ref_key(ref)
    require(r['refs'] == sorted(set(r['refs'])))
    require(r['key'] not in r['refs'])
    if r['kind'] == 'job' and r['state'] == 'SUCCEEDED':
        require('evidence:'+r['evidence_digest'] in r['refs'])
    if r['kind'] == 'control':
        require(sum(x.startswith('job:') for x in r['refs']) == 1)
    if r['kind'] == 'submission' and r['evidence_digest'] is not None:
        require(sum(x.startswith('job:') for x in r['refs']) == 1)
    return r

def validate_inventory(v):
    keys(v, ('schema','profile','source','keeper','store','controller','controller_revision','observation','gates','anchors','records'))
    integer(v['schema'], 1, 1)
    require(v['profile'] == PROFILE)
    require(type(v['source']) is str and v['source'] in ('MODEL_FIXTURE','LIVE_READONLY'))
    for k in ('keeper','store','observation'):
        hex32(v[k])
    if v['controller'] is not None:
        hex32(v['controller'])
    integer(v['controller_revision'], 1)
    keys(v['gates'], GATES)
    for value in v['gates'].values():
        require(type(value) is bool)
    if v['source'] == 'LIVE_READONLY':
        require(not any(v['gates'].values()))
    require(type(v['records']) is list and len(v['records']) <= MAX_RECORDS)
    require(type(v['anchors']) is list and len(v['anchors']) <= MAX_ANCHORS)
    anchors = {}
    for a in v['anchors']:
        keys(a, ('key','proof_digest')); ref_key(a['key']); hex32(a['proof_digest'])
        require(a['key'] not in anchors)
        if v['source'] == 'LIVE_READONLY':
            require(a['key'].split(':')[0] in ('evidence','policy'))
        anchors[a['key']] = a
    require(list(anchors) == sorted(anchors))
    records = {}; intents = set()
    for r in v['records']:
        validate_record(r)
        require(r['key'] not in records and r['key'] not in anchors)
        # A management job's stable signed intent must not alias another job ID.
        if r['kind'] == 'job':
            require(r['intent_digest'] not in intents, 'INTENT_ALIAS')
            intents.add(r['intent_digest'])
        records[r['key']] = r
    require(list(records) == sorted(records))
    for r in records.values():
        if r['kind'] == 'submission' and r['evidence_digest'] is not None:
            target = next(ref for ref in r['refs'] if ref.startswith('job:'))
            if target in records:
                require(records[target]['intent_digest'] == r['evidence_digest'], 'REFERENCE_MISMATCH')
    visiting = set(); visited = set()
    def visit(key):
        require(key not in visiting, 'REFERENCE_CYCLE')
        if key in visited or key in anchors:
            return
        require(key in records, 'DANGLING_REFERENCE')
        visiting.add(key)
        for ref in records[key]['refs']:
            visit(ref)
        visiting.remove(key); visited.add(key)
    for key in records:
        visit(key)
    canonical(v)  # Enforce total serialized budget too.
    return v

def encode_inventory(v) -> bytes:
    return canonical(validate_inventory(v))

def decode_inventory(raw) -> dict:
    return copy.deepcopy(validate_inventory(decode(raw)))

def plan(v, *, archive_limit=64*1024*1024) -> dict:
    """A conservative dry run. Never supplies a path or an executable deletion plan."""
    v = decode_inventory(encode_inventory(v))
    integer(archive_limit, 0, MAX_STORAGE)
    blockers = ['UNMIGRATED:'+k for k, value in sorted(v['gates'].items()) if not value]
    if v['controller'] is None:
        blockers.append('CONTROLLER_UNAVAILABLE')
    needed_by = {r['key']: [] for r in v['records']}
    for r in v['records']:
        if r['state'] not in TERMINAL[r['kind']]:
            blockers.append('NONTERMINAL:'+r['key'])
        if r['reserved_bytes']:
            blockers.append('RESERVATION:'+r['key'])
        for ref in r['refs']:
            if ref in needed_by:
                needed_by[ref].append(r['key'])
    estimate = sum(r['storage_bytes'] for r in v['records'])
    if estimate > archive_limit:
        blockers.append('ARCHIVE_BUDGET')
    return {'schema':1, 'scope':'LOCAL_MODEL_AND_INVENTORY_ONLY',
            'inventory_digest':sha(encode_inventory(v)), 'controller_revision':v['controller_revision'],
            'record_count':len(v['records']), 'keys':[r['key'] for r in v['records']],
            'archive_bytes_estimate':estimate, 'archive_limit':archive_limit,
            'blockers':sorted(blockers), 'needed_by':needed_by,
            'model_ready':not blockers and v['source']=='MODEL_FIXTURE',
            'real_deletion_allowed':False, 'product_qualified':False}
