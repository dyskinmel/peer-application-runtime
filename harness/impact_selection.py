"""Fail-closed impact-based test selection for Harness P4.

Impact analysis may add affected S2 tests to the S0/S1 loop. Uncertainty only
expands selection: stale mappings, unknown paths, unmapped checks, and missing
critical mandatory modules select the full registry rather than omitting tests.
"""
from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from pathlib import Path, PurePosixPath

from .common import HarnessError, atomic_json, file_hash, read_json, safe_path, valid_id
from .test_orchestration import load_registry, plan_entry_ids, run_entry_ids


_POLICY_REL='policy/impact-selection.json'
_BOUND_INPUTS=('plan/tasks.json','policy/checks.json','policy/test-registry.json','policy/test-inventory.json')


def normalize_changed_path(value: str) -> str:
    if not isinstance(value,str) or not value or '\x00' in value or '\\' in value:
        raise HarnessError('IMPACT_PATH_UNSAFE',str(value))
    while value.startswith('./'):
        value=value[2:]
    if not value:
        raise HarnessError('IMPACT_PATH_UNSAFE',str(value))
    p=PurePosixPath(value)
    if p.is_absolute() or any(part in ('','.', '..') for part in p.parts) or ':' in value:
        raise HarnessError('IMPACT_PATH_UNSAFE',value)
    normalized=p.as_posix()
    if normalized.startswith('../') or normalized=='..':
        raise HarnessError('IMPACT_PATH_UNSAFE',value)
    return normalized


def _string_list(value, field: str, *, nonempty: bool=False) -> list[str]:
    if not isinstance(value,list) or (nonempty and not value) or any(not isinstance(x,str) or not x for x in value):
        raise HarnessError('IMPACT_POLICY_INVALID',field)
    if len(value)!=len(set(value)):
        raise HarnessError('IMPACT_POLICY_INVALID',field+':duplicate')
    return list(value)


def load_impact_policy(root: Path) -> dict:
    obj=read_json(safe_path(root,_POLICY_REL))
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('selection_mode')!='IMPACT_SAFE_V1':
        raise HarnessError('IMPACT_POLICY_INVALID','header')
    if obj.get('baseline_max_tier')!='S1':
        raise HarnessError('IMPACT_POLICY_INVALID','baseline_max_tier')
    if obj.get('unknown_behavior')!='CONSERVATIVE_FULL' or obj.get('stale_mapping_behavior')!='CONSERVATIVE_FULL':
        raise HarnessError('IMPACT_POLICY_INVALID','fallback')
    paths=_string_list(obj.get('binding_paths'),'binding_paths',nonempty=True)
    if tuple(paths)!=_BOUND_INPUTS:
        raise HarnessError('IMPACT_POLICY_INVALID','binding_paths')
    bindings=obj.get('bindings')
    if not isinstance(bindings,dict) or set(bindings)!=set(paths) or any(not isinstance(v,str) or len(v)!=64 for v in bindings.values()):
        raise HarnessError('IMPACT_POLICY_INVALID','bindings')
    aliases=obj.get('check_aliases')
    if not isinstance(aliases,dict) or any(not isinstance(k,str) or not k or not isinstance(v,(str,list)) for k,v in aliases.items()):
        raise HarnessError('IMPACT_POLICY_INVALID','check_aliases')
    clean_alias={}
    for k,v in aliases.items():
        vals=[v] if isinstance(v,str) else _string_list(v,'check_aliases:'+k,nonempty=True)
        clean_alias[k.replace('-','_')]=vals
    low_raw=obj.get('low_risk_path_classes',[])
    if not isinstance(low_raw,list): raise HarnessError('IMPACT_POLICY_INVALID','low_risk_path_classes')
    low_classes=[]; low_ids=set()
    for raw in low_raw:
        if not isinstance(raw,dict): raise HarnessError('IMPACT_POLICY_INVALID','low_risk_path_class')
        rid=valid_id(raw.get('id')); klass=raw.get('class'); selection=raw.get('selection')
        if rid in low_ids or not isinstance(klass,str) or not klass or selection!='BASELINE_ONLY':
            raise HarnessError('IMPACT_POLICY_INVALID','low_risk_path_class:'+str(rid))
        low_ids.add(rid)
        patterns=_string_list(raw.get('patterns'),'low_risk_path_class:'+rid+':patterns',nonempty=True)
        low_classes.append({'id':rid,'class':klass,'patterns':patterns,'selection':'BASELINE_ONLY'})
    rules=obj.get('critical_rules')
    if not isinstance(rules,list): raise HarnessError('IMPACT_POLICY_INVALID','critical_rules')
    clean_rules=[]; ids=set()
    for raw in rules:
        if not isinstance(raw,dict):raise HarnessError('IMPACT_POLICY_INVALID','critical_rule')
        rid=valid_id(raw.get('id')); klass=valid_id(raw.get('class'))
        if rid in ids:raise HarnessError('IMPACT_POLICY_INVALID','critical_rule_duplicate:'+rid)
        ids.add(rid)
        patterns=_string_list(raw.get('patterns'),'critical_rule:'+rid+':patterns',nonempty=True)
        modules=_string_list(raw.get('mandatory_modules'),'critical_rule:'+rid+':mandatory_modules',nonempty=True)
        clean_rules.append({'id':rid,'class':klass,'patterns':patterns,'mandatory_modules':modules})
    return {'schema_version':1,'selection_mode':'IMPACT_SAFE_V1','baseline_max_tier':'S1',
            'unknown_behavior':'CONSERVATIVE_FULL','stale_mapping_behavior':'CONSERVATIVE_FULL',
            'binding_paths':paths,'bindings':dict(bindings),'check_aliases':clean_alias,
            'low_risk_path_classes':low_classes,'critical_rules':clean_rules,'product_qualified':False}


def mapping_freshness(root: Path, policy: dict|None=None) -> dict:
    policy=policy or load_impact_policy(root); stale=[]; actual={}
    for rel in policy['binding_paths']:
        try: digest=file_hash(safe_path(root,rel))
        except (HarnessError,OSError):
            digest=None
        actual[rel]=digest
        if digest!=policy['bindings'][rel]:stale.append(rel)
    return {'state':'FRESH' if not stale else 'STALE','stale_paths':stale,'actual_bindings':actual,
            'expected_bindings':dict(policy['bindings'])}


def _registry_maps(root: Path):
    reg=load_registry(root); by_id={e['id']:e for e in reg['entries']}; module_to_ids={}; domain_to_ids={}
    for e in reg['entries']:
        if e['kind']!='CASE':continue
        modules={'.'.join(case.split('.')[:2]) for case in e['case_ids']}
        if len(modules)!=1:raise HarnessError('IMPACT_REGISTRY_MODULE_AMBIGUOUS',e['id'])
        module=next(iter(modules)); module_to_ids.setdefault(module,[]).append(e['id'])
        short=module
        if short.startswith('tests.test_'):short=short[len('tests.test_'):]
        for suffix in ('_registration','_probe'):
            if short.endswith(suffix):short=short[:-len(suffix)]
        domain_to_ids.setdefault(short,[]).append(e['id'])
    return reg,by_id,module_to_ids,domain_to_ids


def _match_allowed(path: str, allowed: str) -> bool:
    is_dir=allowed.endswith('/')
    normalized=normalize_changed_path(allowed[:-1] if is_dir else allowed)
    if normalized==path:return True
    return is_dir and path.startswith(normalized+'/')


def _load_tasks(root: Path) -> list[dict]:
    obj=read_json(safe_path(root,'plan/tasks.json'))
    if not isinstance(obj,dict) or obj.get('version')!=1 or not isinstance(obj.get('tasks'),list):
        raise HarnessError('IMPACT_TASKS_INVALID')
    ids=set(); out=[]
    for raw in obj['tasks']:
        if not isinstance(raw,dict):raise HarnessError('IMPACT_TASKS_INVALID','task')
        tid=valid_id(raw.get('id'))
        if tid in ids:raise HarnessError('IMPACT_TASKS_INVALID','duplicate:'+tid)
        ids.add(tid)
        def sl(name):
            value=raw.get(name,[])
            if not isinstance(value,list) or any(not isinstance(x,str) or not x for x in value):
                raise HarnessError('IMPACT_TASKS_INVALID',tid+':'+name)
            return list(value)
        out.append({'id':tid,'allowed_paths':sl('allowed_paths'),'checks':sl('checks'),
                    'work_packages':sl('work_packages'),'requirements':sl('requirements'),
                    'related_requirements':sl('related_requirements'),
                    'implementation_depends_on':sl('implementation_depends_on'),
                    'verification_depends_on':sl('verification_depends_on')})
    return out


def _critical_matches(paths: list[str], policy: dict) -> list[dict]:
    out=[]
    for rule in policy['critical_rules']:
        hits=sorted({p for p in paths for pattern in rule['patterns'] if fnmatch.fnmatchcase(p,pattern)})
        if hits:out.append({**rule,'matched_paths':hits})
    return out


def _low_risk_classes(paths: list[str], policy: dict) -> dict[str,str]:
    out={}
    for path in paths:
        matches=[]
        for rule in policy.get('low_risk_path_classes',[]):
            if any(fnmatch.fnmatchcase(path,pattern) for pattern in rule['patterns']): matches.append(rule['class'])
        unique=sorted(set(matches))
        if len(unique)>1: raise HarnessError('IMPACT_POLICY_INVALID','low_risk_overlap:'+path)
        if unique: out[path]=unique[0]
    return out


def _check_to_entries(check_id: str, domain_to_ids: dict[str,list[str]], aliases: dict[str,list[str]]) -> list[str]:
    normalized=check_id.replace('-','_')
    candidates=[]
    for domain,ids in domain_to_ids.items():
        if normalized==domain or normalized.startswith(domain+'_'):
            candidates.append((len(domain),domain,ids))
    for prefix,targets in aliases.items():
        if normalized==prefix or normalized.startswith(prefix+'_'):
            ids=[]
            for target in targets:
                ids.extend(domain_to_ids.get(target,[]))
            if ids:candidates.append((len(prefix),prefix,ids))
    if not candidates:return []
    best=max(x[0] for x in candidates); ids=[]
    # deterministic union of all equally-specific mappings
    for size,prefix,found in candidates:
        if size==best:ids.extend(found)
    return sorted(set(ids))


def _affected_tasks(tasks: list[dict], direct_ids: set[str]) -> tuple[set[str],list[dict]]:
    by={t['id']:t for t in tasks}; reverse={tid:set() for tid in by}
    edges=[]
    for t in tasks:
        for field in ('implementation_depends_on','verification_depends_on'):
            for dep in t[field]:
                if dep in by:
                    reverse[dep].add(t['id'])
                    edges.append({'from':dep,'to':t['id'],'kind':field})
    affected=set(direct_ids); queue=sorted(direct_ids)
    while queue:
        cur=queue.pop(0)
        for nxt in sorted(reverse.get(cur,())):
            if nxt not in affected:
                affected.add(nxt);queue.append(nxt)
    used=[e for e in edges if e['from'] in affected and e['to'] in affected]
    return affected,sorted(used,key=lambda x:(x['from'],x['to'],x['kind']))


def select_impact(root: Path, changed_paths: list[str]) -> dict:
    root=root.resolve(); policy=load_impact_policy(root); reg,by_id,module_to_ids,domain_to_ids=_registry_maps(root)
    paths=sorted(set(normalize_changed_path(p) for p in changed_paths))
    registry_order=[e['id'] for e in reg['entries']]
    baseline=[e['id'] for e in reg['entries'] if e['tier'] in ('S0','S1')]
    reasons={eid:[{'kind':'BASELINE_TIER','tier':by_id[eid]['tier']}] for eid in baseline}
    freshness=mapping_freshness(root,policy)
    tasks=_load_tasks(root); by_task={t['id']:t for t in tasks}
    critical=_critical_matches(paths,policy); critical_classes=sorted({r['class'] for r in critical})
    low_risk=_low_risk_classes(paths,policy)
    missing_mandatory=[]; mandatory=[]
    for rule in critical:
        for module in rule['mandatory_modules']:
            ids=module_to_ids.get(module,[])
            if not ids:missing_mandatory.append(module);continue
            for eid in ids:
                mandatory.append(eid);reasons.setdefault(eid,[]).append({'kind':'CRITICAL_MANDATORY','class':rule['class'],'rule_id':rule['id']})

    direct=set(); path_owners={}; unresolved=[]
    for path in paths:
        owners=[]
        for task in tasks:
            if any(_match_allowed(path,a) for a in task['allowed_paths']):owners.append(task['id'])
        path_owners[path]=sorted(set(owners))
        direct.update(owners)
        if not owners and path not in low_risk and not any(path in r['matched_paths'] for r in critical):unresolved.append(path)
    affected,dep_edges=_affected_tasks(tasks,direct)
    checks=sorted({c for tid in affected for c in by_task[tid]['checks']})
    wps=sorted({x for tid in affected for x in by_task[tid]['work_packages']})
    reqs=sorted({x for tid in affected for x in by_task[tid]['requirements']+by_task[tid]['related_requirements']})
    mapped={};impact=[];unmapped=[]
    for check in checks:
        ids=_check_to_entries(check,domain_to_ids,policy['check_aliases'])
        if not ids:unmapped.append(check);continue
        mapped[check]=ids
        for eid in ids:
            impact.append(eid);reasons.setdefault(eid,[]).append({'kind':'AFFECTED_CHECK','check_id':check})

    full_reason=None;mode='IMPACT_SAFE_V1'
    if freshness['state']!='FRESH':full_reason='STALE_MAPPING';mode='STALE_MAPPING_CONSERVATIVE_FULL'
    elif missing_mandatory:full_reason='MANDATORY_MAPPING_GAP';mode='MANDATORY_MAPPING_GAP_CONSERVATIVE_FULL'
    elif unresolved:full_reason='UNKNOWN_PATH';mode='UNKNOWN_PATH_CONSERVATIVE_FULL'
    elif unmapped:full_reason='UNMAPPED_CHECK';mode='UNMAPPED_CHECK_CONSERVATIVE_FULL'
    elif paths and direct and not impact and not mandatory:
        full_reason='NO_VERIFICATION_ROUTE';mode='NO_VERIFICATION_ROUTE_CONSERVATIVE_FULL'
    elif paths and len(low_risk)==len(paths) and not direct and not critical:
        mode='LOW_RISK_BASELINE_ONLY'
    elif not paths:mode='BASELINE_NO_CHANGES'

    selected_set=set(baseline)|set(impact)|set(mandatory)
    if full_reason:
        selected_set=set(registry_order)
        for eid in registry_order:
            reasons.setdefault(eid,[]).append({'kind':'CONSERVATIVE_FULL','reason':full_reason})
    selected=[eid for eid in registry_order if eid in selected_set]
    deferred=[eid for eid in registry_order if eid not in selected_set]
    # Normalize/deduplicate reason records deterministically.
    reason_out={}
    for eid in selected:
        unique={repr(sorted(r.items())):r for r in reasons.get(eid,[])}
        reason_out[eid]=sorted(unique.values(),key=lambda r:tuple(sorted((k,str(v)) for k,v in r.items())))
    graph={'changed_paths':paths,'path_owners':path_owners,'direct_owner_task_ids':sorted(direct),
           'dependency_edges':dep_edges,'affected_task_ids':sorted(affected),'work_package_ids':wps,
           'requirement_ids':reqs,'check_ids':checks,'check_entry_map':mapped,
           'critical_rules':[{'id':r['id'],'class':r['class'],'matched_paths':r['matched_paths']} for r in critical],
           'entry_reasons':reason_out,'mapping_state':freshness['state'],'stale_binding_paths':freshness['stale_paths'],
           'unresolved_paths':sorted(unresolved),'unmapped_check_ids':sorted(unmapped),
           'path_classes':dict(sorted(low_risk.items())),
           'missing_mandatory_modules':sorted(set(missing_mandatory)),'conservative_reason':full_reason}
    return {'selection_mode':mode,'mapping_state':freshness['state'],'stale_binding_paths':freshness['stale_paths'],
            'changed_paths':paths,'direct_owner_task_ids':sorted(direct),'affected_task_ids':sorted(affected),
            'work_package_ids':wps,'requirement_ids':reqs,'check_ids':checks,'unresolved_paths':sorted(unresolved),
            'path_classes':dict(sorted(low_risk.items())),'unmapped_check_ids':sorted(unmapped),'critical_classes':critical_classes,
            'mandatory_entry_ids':[eid for eid in registry_order if eid in set(mandatory)],
            'missing_mandatory_modules':sorted(set(missing_mandatory)),'selected_ids':selected,'deferred_ids':deferred,
            'selected_count':len(selected),'deferred_count':len(deferred),'deferred_status':'NOT_RUN',
            'reason_graph':graph,'product_qualified':False}



def audit_policy(root: Path) -> dict:
    root=root.resolve(); policy=load_impact_policy(root); freshness=mapping_freshness(root,policy)
    _,_,module_to_ids,domain_to_ids=_registry_maps(root); tasks=_load_tasks(root)
    checks=sorted({c for task in tasks for c in task['checks']})
    unmapped=[c for c in checks if not _check_to_entries(c,domain_to_ids,policy['check_aliases'])]
    missing=sorted({module for rule in policy['critical_rules'] for module in rule['mandatory_modules'] if not module_to_ids.get(module)})
    result='PASS' if freshness['state']=='FRESH' and not unmapped and not missing else 'FAIL'
    return {'result':result,'mapping_state':freshness['state'],'stale_binding_paths':freshness['stale_paths'],
            'task_count':len(tasks),'check_count':len(checks),'unmapped_check_ids':unmapped,
            'missing_mandatory_modules':missing,'critical_rule_count':len(policy['critical_rules']),
            'product_qualified':False}

def plan_impact(root: Path, changed_paths: list[str], remaining_seconds: float) -> dict:
    selection=select_impact(root,changed_paths)
    metadata={k:v for k,v in selection.items() if k not in ('selected_ids','deferred_ids','selected_count','deferred_count','deferred_status','product_qualified')}
    return plan_entry_ids(root,selection['selected_ids'],selection['deferred_ids'],remaining_seconds,
                          selection_mode=selection['selection_mode'],metadata=metadata)


def run_impact(root: Path, changed_paths: list[str], remaining_seconds: float) -> dict:
    return run_entry_ids(root,plan_impact(root,changed_paths,remaining_seconds))


def campaign_from_selection(root: Path, selection: dict, campaign_id: str) -> dict:
    cid=valid_id(campaign_id); reg,by_id,_,_=_registry_maps(root); lanes=[]
    for eid in selection['selected_ids']:
        e=by_id[eid]
        cases=list(e['case_ids']) if e['kind']=='CASE' else ['campaign.'+eid]
        argv=[str(Path(__import__('sys').executable)) if x=='{python}' else x for x in e['argv']]
        lanes.append({'id':eid,'argv':argv,'case_ids':cases,'timeout_seconds':e['timeout_seconds'],'tier':e['tier']})
    return {'schema_version':1,'campaign_id':cid,'lanes':lanes}


def write_campaign(path: Path, campaign: dict) -> dict:
    atomic_json(path.resolve(),campaign)
    return {'result':'PASS','output':str(path.resolve()),'campaign_id':campaign['campaign_id'],
            'lane_count':len(campaign['lanes']),'product_qualified':False}


def git_changed_paths(root: Path, base_ref: str|None=None) -> list[str]:
    root=root.resolve(); args=['git','diff','--name-status','-M']
    args.append(base_ref if base_ref else 'HEAD')
    cp=subprocess.run(args,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False)
    if cp.returncode!=0:raise HarnessError('IMPACT_GIT_DIFF_FAILED',cp.stderr.strip()[:300])
    paths=[]
    for line in cp.stdout.splitlines():
        parts=line.split('\t'); status=parts[0] if parts else ''
        if status.startswith(('R','C')) and len(parts)>=3:paths.extend(parts[1:3])
        elif len(parts)>=2:paths.append(parts[1])
    cp2=subprocess.run(['git','ls-files','--others','--exclude-standard'],cwd=root,stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,text=True,check=False)
    if cp2.returncode!=0:raise HarnessError('IMPACT_GIT_DIFF_FAILED',cp2.stderr.strip()[:300])
    paths.extend(cp2.stdout.splitlines())
    return sorted(set(normalize_changed_path(p) for p in paths if p))
