"""P6 fail-closed release/evidence promotion boundary."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
from .common import HarnessError, atomic_json, canonical, digest, file_hash, read_json, safe_path
from .snapshot import snapshot
from .test_orchestration import load_registry
from .verification_ledger import aggregate, campaign_digest
from .advanced_optimization import quarantine_summary

_CONTRACT='P6_RELEASE_EVIDENCE_V1'

def _policy(root:Path)->dict:
    obj=read_json(safe_path(root,'policy/evidence-promotion.json'))
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('promotion_contract')!=_CONTRACT:
        raise HarnessError('PROMOTION_POLICY_INVALID')
    return obj

def _advanced_policy(root:Path)->dict:
    obj=read_json(safe_path(root,'policy/advanced-optimization.json'))
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or not isinstance(obj.get('harness_version'),str):
        raise HarnessError('PROMOTION_HARNESS_VERSION_INVALID')
    return obj

def _git(root:Path)->dict:
    from .artifact_survival import git_identity
    return git_identity(root)

def _fixture_digest(reg:dict)->str:
    rows=[]
    for e in reg['entries']:
        cases=list(e['case_ids']) if e['kind']=='CASE' else ['campaign.'+e['id']]
        rows.append({'id':e['id'],'kind':e['kind'],'case_ids':sorted(cases)})
    return digest(rows)

def release_scope(root:Path)->dict:
    reg=load_registry(root)
    return {'source_digest':snapshot(root)['digest'],'registry_digest':digest(reg),'fixture_digest':_fixture_digest(reg),
            'harness_version':_advanced_policy(root)['harness_version'],'entry_ids':[e['id'] for e in reg['entries']],
            'entry_count':len(reg['entries'])}

def _expected_lane(entry:dict)->dict:
    return {'id':entry['id'],'argv':[sys.executable if x=='{python}' else x for x in entry['argv']],
            'case_ids':list(entry['case_ids']) if entry['kind']=='CASE' else ['campaign.'+entry['id']],
            'timeout_seconds':entry['timeout_seconds'],'tier':entry['tier']}

def _same_lane(a:dict,b:dict)->bool:
    return all(a.get(k)==b.get(k) for k in ('id','argv','case_ids','timeout_seconds','tier'))

def _coverage(root:Path,campaign:dict,shard_plans:list[dict])->dict:
    reg=load_registry(root); by={e['id']:e for e in reg['entries']}; lanes={l.get('id'):l for l in campaign.get('lanes',[]) if isinstance(l,dict)}
    if len(lanes)!=len(campaign.get('lanes',[])): raise HarnessError('PROMOTION_SCOPE_UNEXPECTED','duplicate/invalid lane')
    represented=set(); consumed=set(); shard_parents=[]
    for sp in shard_plans:
        parent=sp.get('parent_test_id')
        if parent not in by or by[parent]['kind']!='CASE' or parent in represented: raise HarnessError('PROMOTION_SHARD_COVERAGE_INVALID',str(parent))
        sl=sp.get('lanes'); count=sp.get('shard_count')
        if not isinstance(sl,list) or not isinstance(count,int) or len(sl)!=count or count<2: raise HarnessError('PROMOTION_SHARD_COVERAGE_INVALID',str(parent))
        seen=[]
        for lane in sl:
            lid=lane.get('id')
            if lid not in lanes or not _same_lane(lanes[lid],lane): raise HarnessError('PROMOTION_SHARD_COVERAGE_INVALID',str(parent))
            consumed.add(lid); seen.extend(lane.get('case_ids',[]))
        expected=list(by[parent]['case_ids'])
        if len(seen)!=len(set(seen)) or sorted(seen)!=sorted(expected) or sp.get('case_set_digest')!=digest(sorted(expected)):
            raise HarnessError('PROMOTION_SHARD_COVERAGE_INVALID',str(parent))
        represented.add(parent); shard_parents.append(parent)
    for eid,e in by.items():
        if eid in represented: continue
        if eid in lanes:
            if not _same_lane(lanes[eid],_expected_lane(e)): raise HarnessError('PROMOTION_SCOPE_DEFINITION_MISMATCH',eid)
            represented.add(eid); consumed.add(eid)
    missing=sorted(set(by)-represented)
    if missing: raise HarnessError('PROMOTION_SCOPE_INCOMPLETE',','.join(missing))
    extra=sorted(set(lanes)-consumed)
    if extra: raise HarnessError('PROMOTION_SCOPE_UNEXPECTED',','.join(extra))
    return {'represented_entry_ids':sorted(represented),'sharded_parent_ids':sorted(shard_parents),'lane_count':len(lanes)}

def _candidate(root:Path,path:Path)->dict:
    from .artifact_survival import read_artifact_status
    status=read_artifact_status(path); src=snapshot(root); git=_git(root)
    if status.get('status')!='PARTIAL': raise HarnessError('PROMOTION_CANDIDATE_STATUS_INVALID',str(status.get('status')))
    if status.get('source',{}).get('digest')!=src['digest'] or status.get('git',{}).get('head')!=git['head']:
        raise HarnessError('PROMOTION_CANDIDATE_STALE')
    if git['dirty'] or status.get('git',{}).get('dirty'): raise HarnessError('PROMOTION_DIRTY_SOURCE')
    return {'sha256':file_hash(path),'size_bytes':path.stat().st_size,'source_digest':src['digest'],'git_head':git['head']}

def _ledger_review(root:Path,ledger:Path,campaign:dict,env_fp:str)->dict:
    try: out=aggregate(root,ledger,campaign,env_fp)
    except HarnessError as exc:
        mapping={'LEDGER_DUPLICATE_LANE':'PROMOTION_EVIDENCE_DUPLICATE','LEDGER_RECEIPT_TAMPERED':'PROMOTION_EVIDENCE_TAMPERED',
                 'LEDGER_SOURCE_STALE':'PROMOTION_EVIDENCE_STALE','LEDGER_ENVIRONMENT_STALE':'PROMOTION_EVIDENCE_STALE',
                 'LEDGER_TEST_DEFINITION_STALE':'PROMOTION_EVIDENCE_STALE','LEDGER_UNEXPECTED_LANE':'PROMOTION_EVIDENCE_UNEXPECTED'}
        raise HarnessError(mapping.get(exc.code,'PROMOTION_EVIDENCE_INVALID'),exc.detail) from exc
    if out['result']=='INCOMPLETE': raise HarnessError('PROMOTION_EVIDENCE_INCOMPLETE',','.join(out['missing_lane_ids']))
    if out['result']!='PASS': raise HarnessError('PROMOTION_EVIDENCE_NONPASS')
    receipts=ledger.resolve()/'receipts'
    out['receipt_sha256']={p.stem:file_hash(p) for p in sorted(receipts.glob('*.json'))}
    return out

def _record_seal(body:dict)->str: return hashlib.sha256(canonical(body)).hexdigest()

def review_promotion(root:Path,candidate:Path,campaign:dict,ledger:Path,environment_fingerprint:str,*,
                     shard_plans:list[dict]|None=None,sample_plans:list[dict]|None=None,cache_claims:list[dict]|None=None,now:float|None=None)->dict:
    root=root.resolve(); _policy(root)
    if sample_plans: raise HarnessError('PROMOTION_SAMPLED_EVIDENCE_FORBIDDEN')
    if cache_claims: raise HarnessError('PROMOTION_CACHE_NOT_EVIDENCE')
    cand=_candidate(root,candidate.resolve()); cov=_coverage(root,campaign,list(shard_plans or []))
    qs=quarantine_summary(root,now=now)
    if qs['active_ids'] or qs['expired_ids']: raise HarnessError('PROMOTION_QUARANTINE_UNRESOLVED',','.join(qs['active_ids']+qs['expired_ids']))
    agg=_ledger_review(root,ledger.resolve(),campaign,environment_fingerprint)
    scope=release_scope(root)
    body={'schema_version':1,'kind':'HARNESS_PROMOTION_RECORD','result':'PASS','promotion_status':'VERIFIED','promotion_contract':_CONTRACT,
          'binding':{**scope,'environment_fingerprint':environment_fingerprint,'campaign_digest':campaign_digest(campaign)},
          'candidate':cand,'coverage':cov,'evidence':{'pass_count':agg['pass_count'],'expected_count':agg['expected_count'],'lane_statuses':agg['lane_statuses'],'receipt_sha256':agg['receipt_sha256']},
          'quarantine':{'active_ids':[],'expired_ids':[]},'independent_review_ready':True,'product_qualified':False,
          'nonclaims':['native/device qualification','publisher authenticity','independent security review','production readiness']}
    return {**body,'seal_sha256':_record_seal(body)}

def write_promotion_record(root:Path,output:Path,candidate:Path,campaign:dict,ledger:Path,environment_fingerprint:str,**kwargs)->dict:
    obj=review_promotion(root,candidate,campaign,ledger,environment_fingerprint,**kwargs);atomic_json(output.resolve(),obj);return obj

def verify_promotion_record(root:Path,path:Path,candidate:Path|None=None)->dict:
    obj=read_json(path.resolve())
    if not isinstance(obj,dict) or obj.get('kind')!='HARNESS_PROMOTION_RECORD' or obj.get('schema_version')!=1: raise HarnessError('PROMOTION_RECORD_INVALID')
    seal=obj.get('seal_sha256');body={k:v for k,v in obj.items() if k!='seal_sha256'}
    if not isinstance(seal,str) or seal!=_record_seal(body): raise HarnessError('PROMOTION_RECORD_TAMPERED')
    if obj.get('result')!='PASS' or obj.get('promotion_status')!='VERIFIED' or obj.get('promotion_contract')!=_CONTRACT: raise HarnessError('PROMOTION_RECORD_INVALID')
    scope=release_scope(root);binding=obj.get('binding',{})
    for k in ('source_digest','registry_digest','fixture_digest','harness_version'):
        if binding.get(k)!=scope[k]: raise HarnessError('PROMOTION_RECORD_STALE',k)
    git=_git(root)
    if git['dirty'] or obj.get('candidate',{}).get('git_head')!=git['head']: raise HarnessError('PROMOTION_RECORD_STALE','git')
    if candidate is not None:
        candidate=candidate.resolve()
        if not candidate.is_file() or file_hash(candidate)!=obj.get('candidate',{}).get('sha256'):
            raise HarnessError('PROMOTION_RECORD_CANDIDATE_MISMATCH')
    return {'result':'PASS','promotion_status':'VERIFIED','promotion_contract':_CONTRACT,'record_digest':digest(obj),'binding':binding,'candidate':obj['candidate'],'product_qualified':False}
