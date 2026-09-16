"""P5B advanced optimization primitives.

These mechanisms optimize execution/reuse without weakening verification:
cache hits are not evidence, samples are proxy-only, quarantine is never PASS,
and shards are ordinary P2 lanes with exact case membership.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from .common import HarnessError, atomic_json, canonical, digest, read_json, safe_path, valid_id
from .test_orchestration import load_registry
from .snapshot import snapshot


def _policy(root: Path) -> dict:
    obj = read_json(safe_path(root, 'policy/advanced-optimization.json'))
    if not isinstance(obj, dict) or obj.get('schema_version') != 1:
        raise HarnessError('ADVANCED_OPTIMIZATION_POLICY_INVALID')
    return obj


def _entry(root: Path, test_id: str) -> dict:
    test_id = valid_id(test_id)
    for row in load_registry(root)['entries']:
        if row['id'] == test_id:
            return row
    raise HarnessError('TEST_REGISTRY_UNKNOWN_ID', test_id)


def _rank_cases(test_id: str, cases: list[str]) -> list[str]:
    return sorted(cases, key=lambda case: hashlib.sha256(canonical({
        'algorithm': 'sha256-rank-round-robin-v1',
        'test_id': test_id,
        'case_id': case,
    })).hexdigest())


def shard_plan(root: Path, test_id: str, shard_count: int, campaign_id: str) -> dict:
    policy = _policy(root)
    entry = _entry(root, test_id)
    campaign_id = valid_id(campaign_id)
    if entry['kind'] != 'CASE':
        raise HarnessError('SHARD_ENTRY_NOT_CASE', test_id)
    cases = list(entry['case_ids'])
    max_shards = int(policy['sharding']['max_shards'])
    if isinstance(shard_count, bool) or not isinstance(shard_count, int) or shard_count < 2 or shard_count > max_shards or shard_count > len(cases):
        raise HarnessError('SHARD_COUNT_INVALID', str(shard_count))
    buckets = [[] for _ in range(shard_count)]
    for index, case in enumerate(_rank_cases(test_id, cases)):
        buckets[index % shard_count].append(case)
    lanes = []
    parent_token = digest({'test_id': test_id})[:12]
    for index, bucket in enumerate(buckets, start=1):
        lane_id = f'shard-{parent_token}-{index:02d}of{shard_count:02d}'
        lanes.append({
            'id': lane_id,
            'argv': [str(Path(sys.executable)), '-m', 'unittest', *bucket],
            'case_ids': bucket,
            'timeout_seconds': entry['timeout_seconds'],
            'tier': entry['tier'],
        })
    return {
        'schema_version': 1,
        'campaign_id': campaign_id,
        'lanes': lanes,
        'parent_test_id': test_id,
        'shard_count': shard_count,
        'sharding_algorithm': policy['sharding']['algorithm'],
        'case_set_digest': digest(sorted(cases)),
        'product_qualified': False,
    }


def sample_plan(items: list[str], seed: str, corpus_version: str, count: int) -> dict:
    if not isinstance(items, list) or not items or any(not isinstance(x, str) or not x for x in items) or len(items) != len(set(items)):
        raise HarnessError('SAMPLE_ITEMS_INVALID')
    if not isinstance(seed, str) or not seed or not isinstance(corpus_version, str) or not corpus_version:
        raise HarnessError('SAMPLE_DEFINITION_INVALID')
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > len(items):
        raise HarnessError('SAMPLE_COUNT_INVALID', str(count))
    algorithm = 'sha256-rank-v1'
    ranked = sorted(items, key=lambda item: hashlib.sha256(canonical({
        'algorithm': algorithm,
        'seed': seed,
        'corpus_version': corpus_version,
        'item_id': item,
    })).hexdigest())
    selected = ranked[:count]
    deferred = ranked[count:]
    definition = {
        'algorithm': algorithm,
        'seed': seed,
        'corpus_version': corpus_version,
        'item_count': len(items),
        'sample_count': count,
        'selected_items': selected,
        'deferred_items': deferred,
    }
    return {
        'schema_version': 1,
        **definition,
        'sample_digest': digest(definition),
        'deferred_status': 'NOT_RUN',
        'verification_claim': 'SAMPLED_PROXY_NOT_VERIFICATION',
        'product_qualified': False,
    }


_QUARANTINE_REL = '.harness/flaky-quarantine.json'
_QUARANTINE_STATUSES = ('INVESTIGATING','QUARANTINED')

def _quarantine_core(entries: dict) -> dict:
    return {'schema_version':1,'kind':'HARNESS_FLAKY_QUARANTINE','entries':entries}

def _quarantine_seal(core: dict) -> str:
    return hashlib.sha256(canonical(core)).hexdigest()

def _load_quarantine(root: Path) -> dict:
    path=safe_path(root,_QUARANTINE_REL)
    if not path.exists():
        core=_quarantine_core({})
        return {**core,'seal_sha256':_quarantine_seal(core)}
    obj=read_json(path)
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('kind')!='HARNESS_FLAKY_QUARANTINE' or not isinstance(obj.get('entries'),dict):
        raise HarnessError('QUARANTINE_STATE_INVALID')
    seal=obj.get('seal_sha256')
    core={k:v for k,v in obj.items() if k!='seal_sha256'}
    if not isinstance(seal,str) or seal!=_quarantine_seal(core):
        raise HarnessError('QUARANTINE_STATE_TAMPERED')
    return obj

def _save_quarantine(root: Path, entries: dict) -> None:
    core=_quarantine_core(entries)
    atomic_json(safe_path(root,_QUARANTINE_REL),{**core,'seal_sha256':_quarantine_seal(core)})

def set_quarantine(root: Path, test_id: str, owner: str, expires_at: float, release_blocker: bool, *, status: str='QUARANTINED', now: float|None=None) -> dict:
    _entry(root,test_id)
    owner=valid_id(owner)
    now=float(time.time() if now is None else now)
    if isinstance(expires_at,bool) or not isinstance(expires_at,(int,float)) or float(expires_at)<=now:
        raise HarnessError('QUARANTINE_EXPIRY_INVALID',str(expires_at))
    if not isinstance(release_blocker,bool):
        raise HarnessError('QUARANTINE_RELEASE_BLOCKER_INVALID')
    if status not in _QUARANTINE_STATUSES:
        raise HarnessError('QUARANTINE_STATUS_INVALID',str(status))
    obj=_load_quarantine(root); entries=dict(obj['entries']); previous=entries.get(test_id,{})
    row={
        'test_id':test_id,
        'owner':owner,
        'first_seen_at':float(previous.get('first_seen_at',now)),
        'updated_at':now,
        'expires_at':float(expires_at),
        'release_blocker':release_blocker,
        'status':status,
        'runs':int(previous.get('runs',0)),
        'failures':int(previous.get('failures',0)),
    }
    row['reproduction_rate']=(row['failures']/row['runs']) if row['runs'] else 0.0
    entries[test_id]=row; _save_quarantine(root,entries)
    return dict(row)

def observe_quarantine(root: Path, test_id: str, failed: bool, *, now: float|None=None) -> dict:
    if not isinstance(failed,bool):
        raise HarnessError('QUARANTINE_OBSERVATION_INVALID')
    obj=_load_quarantine(root); entries=dict(obj['entries'])
    if test_id not in entries:
        raise HarnessError('QUARANTINE_UNKNOWN_ID',test_id)
    row=dict(entries[test_id]); row['runs']=int(row.get('runs',0))+1; row['failures']=int(row.get('failures',0))+(1 if failed else 0)
    row['reproduction_rate']=row['failures']/row['runs']; row['updated_at']=float(time.time() if now is None else now)
    entries[test_id]=row; _save_quarantine(root,entries)
    return dict(row)

def quarantine_summary(root: Path, *, now: float|None=None) -> dict:
    obj=_load_quarantine(root); now=float(time.time() if now is None else now)
    entries={k:dict(v) for k,v in obj['entries'].items()}
    active=[]; expired=[]; blockers=[]
    for test_id,row in sorted(entries.items()):
        if float(row['expires_at'])<=now:
            expired.append(test_id)
        else:
            active.append(test_id)
            if row.get('release_blocker'):
                blockers.append(test_id)
    return {'schema_version':1,'entries':entries,'active_ids':active,'expired_ids':expired,
            'release_blocker_ids':blockers,'release_eligible':not blockers and not expired,
            'verification_status':'NOT_EVIDENCE','product_qualified':False}

def apply_quarantine(root: Path, selected_ids: list[str], *, now: float|None=None) -> dict:
    if len(selected_ids)!=len(set(selected_ids)):
        raise HarnessError('QUARANTINE_SELECTION_DUPLICATE')
    known={e['id'] for e in load_registry(root)['entries']}
    unknown=sorted(set(selected_ids)-known)
    if unknown:
        raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',','.join(unknown))
    summary=quarantine_summary(root,now=now); active=set(summary['active_ids']); expired=set(summary['expired_ids'])
    quarantined=[x for x in selected_ids if x in active]
    run_ids=[x for x in selected_ids if x not in active]
    return {'selected_ids':list(selected_ids),'run_ids':run_ids,'quarantined_ids':quarantined,
            'expired_ids':[x for x in selected_ids if x in expired],'quarantined_status':'QUARANTINED',
            'release_blocker_ids':[x for x in quarantined if x in set(summary['release_blocker_ids'])],
            'release_eligible':summary['release_eligible'] and not quarantined,
            'verification_status':'NOT_EVIDENCE','product_qualified':False}


_CACHE_NAMESPACES = ('BUILD','FIXTURE')
_HEX64 = re.compile(r'^[0-9a-f]{64}$')

def _cache_binding(root: Path, namespace: str, user_key: str, definition_digest: str,
                   fixture_digest: str, environment_fingerprint: str) -> dict:
    policy=_policy(root)
    if namespace not in _CACHE_NAMESPACES:
        raise HarnessError('CACHE_NAMESPACE_FORBIDDEN',str(namespace))
    user_key=valid_id(user_key)
    for name,value in (('definition_digest',definition_digest),('fixture_digest',fixture_digest)):
        if not isinstance(value,str) or not _HEX64.fullmatch(value):
            raise HarnessError('CACHE_BINDING_INVALID',name)
    if not isinstance(environment_fingerprint,str) or not environment_fingerprint:
        raise HarnessError('CACHE_BINDING_INVALID','environment_fingerprint')
    return {
        'schema_version':1,
        'namespace':namespace,
        'user_key':user_key,
        'source_digest':snapshot(root)['digest'],
        'definition_digest':definition_digest,
        'fixture_digest':fixture_digest,
        'environment_fingerprint':environment_fingerprint,
        'harness_version':str(policy['harness_version']),
    }

def _cache_paths(root: Path, binding: dict) -> tuple[str,Path,Path,Path]:
    key=digest(binding)
    rel=f'.harness/cache/{binding["namespace"].lower()}/{key}'
    directory=safe_path(root,rel)
    metadata=safe_path(root,rel+'/metadata.json')
    payload=safe_path(root,rel+'/payload.bin')
    return key,directory,metadata,payload

def _cache_metadata_core(binding: dict, payload: bytes) -> dict:
    return {**binding,'kind':'HARNESS_NON_EVIDENCE_CACHE','payload_sha256':hashlib.sha256(payload).hexdigest(),
            'payload_bytes':len(payload),'verification_status':'NOT_EVIDENCE','product_qualified':False}

def _cache_metadata_seal(core: dict) -> str:
    return hashlib.sha256(canonical(core)).hexdigest()

def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.tmp-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        if os.name=='posix':
            dfd=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(dfd)
            finally:os.close(dfd)
    finally:
        if os.path.exists(name):os.unlink(name)

def cache_put(root: Path, namespace: str, user_key: str, payload: bytes, definition_digest: str,
              fixture_digest: str, environment_fingerprint: str) -> dict:
    if not isinstance(payload,(bytes,bytearray)):
        raise HarnessError('CACHE_PAYLOAD_INVALID')
    payload=bytes(payload)
    binding=_cache_binding(root,namespace,user_key,definition_digest,fixture_digest,environment_fingerprint)
    key,directory,metadata_path,payload_path=_cache_paths(root,binding)
    directory.mkdir(parents=True,exist_ok=True)
    core=_cache_metadata_core(binding,payload)
    _atomic_bytes(payload_path,payload)
    atomic_json(metadata_path,{**core,'metadata_seal_sha256':_cache_metadata_seal(core)})
    return {'result':'STORED','cache_key':key,'metadata_path':str(metadata_path),'payload_path':str(payload_path),
            'payload_sha256':core['payload_sha256'],'verification_status':'NOT_EVIDENCE','product_qualified':False}

def cache_get(root: Path, namespace: str, user_key: str, definition_digest: str,
              fixture_digest: str, environment_fingerprint: str) -> dict:
    binding=_cache_binding(root,namespace,user_key,definition_digest,fixture_digest,environment_fingerprint)
    key,directory,metadata_path,payload_path=_cache_paths(root,binding)
    base={'cache_key':key,'verification_status':'NOT_EVIDENCE','product_qualified':False}
    if not directory.exists():
        return {**base,'result':'MISS','reason':'CACHE_MISS_BINDING'}
    if not directory.is_dir() or not metadata_path.exists() or not payload_path.exists():
        raise HarnessError('CACHE_ENTRY_INVALID',key)
    obj=read_json(metadata_path)
    if not isinstance(obj,dict):raise HarnessError('CACHE_METADATA_TAMPERED',key)
    seal=obj.get('metadata_seal_sha256'); core={k:v for k,v in obj.items() if k!='metadata_seal_sha256'}
    if not isinstance(seal,str) or seal!=_cache_metadata_seal(core):
        raise HarnessError('CACHE_METADATA_TAMPERED',key)
    for field,value in binding.items():
        if core.get(field)!=value:
            raise HarnessError('CACHE_METADATA_TAMPERED',key+':'+field)
    payload=payload_path.read_bytes()
    if core.get('payload_sha256')!=hashlib.sha256(payload).hexdigest() or core.get('payload_bytes')!=len(payload):
        raise HarnessError('CACHE_PAYLOAD_TAMPERED',key)
    if core.get('verification_status')!='NOT_EVIDENCE' or core.get('kind')!='HARNESS_NON_EVIDENCE_CACHE':
        raise HarnessError('CACHE_METADATA_TAMPERED',key+':claim')
    return {**base,'result':'HIT','metadata_path':str(metadata_path),'payload_path':str(payload_path),
            'payload_sha256':core['payload_sha256'],'payload_bytes':core['payload_bytes']}
