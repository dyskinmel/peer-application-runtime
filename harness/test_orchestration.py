"""Budget-aware test registry and duration history for Harness P3.

P3 selects by explicit tier only. Impact-based omission is deliberately deferred
until P4; unselected higher-tier tests are NOT_RUN, never inferred PASS.
"""
from __future__ import annotations

import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .artifact_survival import cycle_budget_from_policy
from .common import HarnessError, atomic_json, clean_env, read_json, safe_path, valid_id

TIERS=('S0','S1','S2','S3')
KINDS=('CASE','CAMPAIGN')
_HISTORY_REL='.harness/test-duration-history.json'


def _positive_number(value, field: str) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or value<=0:
        raise HarnessError('TEST_REGISTRY_INVALID',field)
    return float(value)


def load_registry(root: Path) -> dict:
    obj=read_json(safe_path(root,'policy/test-registry.json'))
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('tiers')!=list(TIERS):
        raise HarnessError('TEST_REGISTRY_INVALID','header')
    entries=obj.get('entries')
    if not isinstance(entries,list) or not entries:
        raise HarnessError('TEST_REGISTRY_INVALID','entries')
    seen_ids=set(); seen_cases=set(); cleaned=[]
    for raw in entries:
        if not isinstance(raw,dict): raise HarnessError('TEST_REGISTRY_INVALID','entry')
        eid=valid_id(raw.get('id'))
        if eid in seen_ids: raise HarnessError('TEST_REGISTRY_DUPLICATE_ID',eid)
        seen_ids.add(eid)
        kind=raw.get('kind'); tier=raw.get('tier')
        if kind not in KINDS or tier not in TIERS: raise HarnessError('TEST_REGISTRY_INVALID',eid+':kind/tier')
        cases=raw.get('case_ids')
        if not isinstance(cases,list) or any(not isinstance(x,str) or not x for x in cases) or len(cases)!=len(set(cases)):
            raise HarnessError('TEST_REGISTRY_INVALID',eid+':case_ids')
        if kind=='CASE' and not cases: raise HarnessError('TEST_REGISTRY_INVALID',eid+':case_ids')
        if kind=='CAMPAIGN' and cases: raise HarnessError('TEST_REGISTRY_INVALID',eid+':campaign_cases')
        for case in cases:
            if case in seen_cases: raise HarnessError('TEST_REGISTRY_DUPLICATE_CASE',case)
            seen_cases.add(case)
        argv=raw.get('argv')
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) or not x for x in argv):
            raise HarnessError('TEST_REGISTRY_INVALID',eid+':argv')
        timeout=_positive_number(raw.get('timeout_seconds'),eid+':timeout_seconds')
        estimate=_positive_number(raw.get('estimate_seconds'),eid+':estimate_seconds')
        parallel=raw.get('parallel_safe')
        if not isinstance(parallel,bool): raise HarnessError('TEST_REGISTRY_INVALID',eid+':parallel_safe')
        weights=[]
        for f in ('cpu_weight','memory_weight','io_weight'):
            v=raw.get(f)
            if isinstance(v,bool) or not isinstance(v,int) or v<1 or v>100:
                raise HarnessError('TEST_REGISTRY_INVALID',eid+':'+f)
            weights.append(v)
        exclusive=raw.get('exclusive_resource')
        if exclusive is not None:
            exclusive=valid_id(exclusive)
        cleaned.append({
            'id':eid,'kind':kind,'case_ids':cases,'tier':tier,'argv':argv,
            'timeout_seconds':timeout,'estimate_seconds':estimate,'parallel_safe':parallel,
            'cpu_weight':weights[0],'memory_weight':weights[1],'io_weight':weights[2],
            'exclusive_resource':exclusive,
        })
    default=obj.get('default_max_tier')
    if default not in TIERS: raise HarnessError('TEST_REGISTRY_INVALID','default_max_tier')
    limit=obj.get('history_limit')
    if isinstance(limit,bool) or not isinstance(limit,int) or limit<1 or limit>1000:
        raise HarnessError('TEST_REGISTRY_INVALID','history_limit')
    return {'schema_version':1,'tiers':list(TIERS),'entries':cleaned,'default_max_tier':default,
            'history_limit':limit,'product_qualified':False}


def _entry_map(root: Path) -> dict[str,dict]:
    return {x['id']:x for x in load_registry(root)['entries']}


def select_by_tier(root: Path, max_tier: str|None=None) -> dict:
    reg=load_registry(root); tier=max_tier or reg['default_max_tier']
    if tier not in TIERS: raise HarnessError('TEST_TIER_INVALID',str(tier))
    max_index=TIERS.index(tier)
    selected=[x for x in reg['entries'] if TIERS.index(x['tier'])<=max_index]
    deferred=[x for x in reg['entries'] if TIERS.index(x['tier'])>max_index]
    return {'max_tier':tier,'selected_ids':[x['id'] for x in selected],
            'deferred_ids':[x['id'] for x in deferred],'deferred_status':'NOT_RUN',
            'selected_count':len(selected),'deferred_count':len(deferred),'product_qualified':False}


def _history_path(root: Path) -> Path:
    return safe_path(root,_HISTORY_REL)


def _load_history(root: Path) -> dict:
    path=_history_path(root)
    if not path.exists(): return {'schema_version':1,'tests':{}}
    obj=read_json(path)
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or not isinstance(obj.get('tests'),dict):
        raise HarnessError('TEST_DURATION_HISTORY_INVALID')
    return obj


def _stats(samples: list[float]) -> dict:
    ordered=sorted(samples); n=len(ordered)
    p95=ordered[max(0,math.ceil(.95*n)-1)]
    return {'last_seconds':samples[-1],'median_seconds':statistics.median(ordered),
            'p95_seconds':p95,'sample_count':n}


def record_duration(root: Path, test_id: str, duration_seconds: float) -> dict:
    reg=load_registry(root); entries={x['id']:x for x in reg['entries']}
    if test_id not in entries: raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',test_id)
    duration=_positive_number(duration_seconds,'duration_seconds')
    obj=_load_history(root); row=obj['tests'].setdefault(test_id,{'samples_seconds':[]})
    samples=row.get('samples_seconds')
    if not isinstance(samples,list) or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<=0 for x in samples):
        raise HarnessError('TEST_DURATION_HISTORY_INVALID',test_id)
    samples=[float(x) for x in samples]+[duration]
    samples=samples[-reg['history_limit']:]
    row['samples_seconds']=samples
    row.update(_stats(samples))
    atomic_json(_history_path(root),obj)
    return dict(row)


def duration_stats(root: Path, test_id: str) -> dict:
    if test_id not in _entry_map(root): raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',test_id)
    obj=_load_history(root); row=obj['tests'].get(test_id)
    if row is None: return {'last_seconds':None,'median_seconds':None,'p95_seconds':None,'sample_count':0}
    samples=row.get('samples_seconds')
    if not isinstance(samples,list) or not samples: raise HarnessError('TEST_DURATION_HISTORY_INVALID',test_id)
    return _stats([float(x) for x in samples])


def estimate_entry_seconds(root: Path, test_id: str) -> float:
    entry=_entry_map(root).get(test_id)
    if entry is None: raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',test_id)
    stats=duration_stats(root,test_id)
    return float(stats['p95_seconds'] if stats['p95_seconds'] is not None else entry['estimate_seconds'])


def plan_entry_ids(root: Path, selected_ids: list[str], deferred_ids: list[str],
                   remaining_seconds: float, *, selection_mode: str, metadata: dict|None=None) -> dict:
    entries=_entry_map(root)
    if len(selected_ids)!=len(set(selected_ids)) or len(deferred_ids)!=len(set(deferred_ids)):
        raise HarnessError('TEST_SELECTION_DUPLICATE_ID')
    unknown=sorted((set(selected_ids)|set(deferred_ids))-set(entries))
    if unknown: raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',','.join(unknown))
    overlap=sorted(set(selected_ids)&set(deferred_ids))
    if overlap: raise HarnessError('TEST_SELECTION_OVERLAP',','.join(overlap))
    estimates={eid:estimate_entry_seconds(root,eid) for eid in selected_ids}
    total=sum(estimates.values())
    budget=cycle_budget_from_policy(root,remaining_seconds,total)
    resources=[]
    for eid in selected_ids:
        e=entries[eid]
        resources.append({'id':eid,'tier':e['tier'],'timeout_seconds':e['timeout_seconds'],
                          'parallel_safe':e['parallel_safe'],'cpu_weight':e['cpu_weight'],
                          'memory_weight':e['memory_weight'],'io_weight':e['io_weight'],
                          'exclusive_resource':e['exclusive_resource']})
    out={'selected_ids':list(selected_ids),'deferred_ids':list(deferred_ids),'deferred_status':'NOT_RUN',
         'selected_count':len(selected_ids),'deferred_count':len(deferred_ids),
         'product_qualified':False,**budget,'estimated_work_seconds':total,'estimated_by_id':estimates,
         'resources':resources,'scheduler_implemented':False,'selection_mode':selection_mode}
    if metadata: out.update(metadata)
    return out


def plan_tier(root: Path, max_tier: str|None, remaining_seconds: float) -> dict:
    sel=select_by_tier(root,max_tier)
    return plan_entry_ids(root,sel['selected_ids'],sel['deferred_ids'],remaining_seconds,
                          selection_mode='TIER_ONLY_NO_IMPACT_ANALYSIS',
                          metadata={'max_tier':sel['max_tier']})


def _command_argv(entry: dict) -> list[str]:
    return [sys.executable if x=='{python}' else x for x in entry['argv']]


def run_entry_ids(root: Path, plan: dict) -> dict:
    if plan['action']!='START_WORK':
        return {**plan,'result':'INCOMPLETE','run_count':0,'lane_statuses':{},
                'selected_scope_complete':False}
    entries=_entry_map(root); statuses={}; started=time.monotonic(); run_count=0
    selected=list(plan['selected_ids']); deferred=list(plan['deferred_ids'])
    for index,eid in enumerate(selected):
        entry=entries[eid]
        elapsed=time.monotonic()-started
        work_left=max(0.0,plan['usable_work_seconds']-elapsed)
        estimate=estimate_entry_seconds(root,eid)
        if work_left<=0 or estimate>work_left:
            remaining=selected[index:]
            return {**plan,'action':'DRAIN_AND_CHECKPOINT','reason':'RUNTIME_BUDGET_EXHAUSTED',
                    'result':'INCOMPLETE','run_count':run_count,'lane_statuses':statuses,
                    'deferred_ids':remaining+deferred,'deferred_status':'NOT_RUN',
                    'selected_scope_complete':False}
        timeout=min(float(entry['timeout_seconds']),work_left)
        t0=time.monotonic(); rc=None
        try:
            cp=subprocess.run(_command_argv(entry),cwd=root,env=clean_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=timeout,check=False,start_new_session=True)
            rc=cp.returncode; status='PASS' if rc==0 else 'FAIL'
        except subprocess.TimeoutExpired:
            status='TIMEOUT'
        except OSError:
            status='ENVIRONMENT_BLOCKED'
        duration=max(0.000001,time.monotonic()-t0)
        record_duration(root,eid,duration)
        statuses[eid]=status; run_count+=1
    complete=all(v=='PASS' for v in statuses.values()) and run_count==len(selected)
    result='PASS_SELECTED_SCOPE' if complete else 'FAIL_OR_INCOMPLETE'
    return {**plan,'result':result,'run_count':run_count,'lane_statuses':statuses,
            'selected_scope_complete':complete,'deferred_status':'NOT_RUN'}


def run_tier(root: Path, max_tier: str|None, remaining_seconds: float) -> dict:
    return run_entry_ids(root,plan_tier(root,max_tier,remaining_seconds))
