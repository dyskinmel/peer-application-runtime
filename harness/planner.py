"""Planning only: implementation readiness never confers product qualification."""
from __future__ import annotations
from pathlib import Path
from .common import HarnessError, read_json, safe_path, valid_id

def load_tasks(root: Path) -> dict:
    rows=read_json(safe_path(root,'plan/tasks.json')).get('tasks',[])
    tasks={}
    try:
        for t in rows:
            valid_id(t['id'])
            if t['id'] in tasks: raise ValueError('duplicate task '+t['id'])
            if t['lane'] not in ('LOCAL','EXTERNAL'): raise ValueError('invalid lane')
            for f in ('checks','implementation_depends_on','verification_depends_on','qualification_depends_on','requirements','acceptance_ids','required_capabilities','context','allowed_paths'):
                if not isinstance(t.get(f),list): raise ValueError('missing list '+f)
            for p in t['allowed_paths']+t['context']:
                safe_path(root,p)
            if not t.get('definition_of_done'): raise ValueError('no acceptance contract')
            tasks[t['id']]=t
        seen=set(); active=set()
        def visit(i):
            if i in active: raise ValueError('dependency cycle '+i)
            if i in seen:return
            active.add(i);t=tasks[i]
            for d in set(t['implementation_depends_on']+t['verification_depends_on']):
                if d=='LOCAL-CLOSURE':
                    if t['lane']!='EXTERNAL':raise ValueError('local closure on local task')
                    continue
                if d not in tasks:raise ValueError('unknown dependency '+d)
                if t['lane']=='LOCAL' and tasks[d]['lane']=='EXTERNAL':raise ValueError('local blocked by external')
                visit(d)
            active.remove(i);seen.add(i)
        for i in tasks:visit(i)
    except (KeyError,TypeError,ValueError) as exc: raise HarnessError('INVALID_PLAN',str(exc)) from exc
    return tasks

def select(root: Path, capabilities: dict, completed: dict) -> dict:
    tasks=load_tasks(root);ready=[];blocked=[];external=[];done=[]
    for t in sorted(tasks.values(),key=lambda t:(t.get('priority',99),t['id'])):
        i=t['id']
        # completed is provided by the verifier; status strings in task files are ignored.
        if i in completed:
            done.append(i);continue
        if t['lane']=='EXTERNAL':external.append({'id':i,'title':t['title'],'reason':'LOCAL_CLOSURE_AND_OPERATOR_APPROVAL_REQUIRED'});continue
        reasons=['DEPENDENCY:'+d for d in set(t['implementation_depends_on']+t['verification_depends_on']) if d not in completed]
        reasons+=['CAPABILITY:'+c for c in t['required_capabilities'] if not capabilities.get(c,False)]
        row={'id':i,'title':t['title'],'verification':'REGISTERED' if t['checks'] else 'NOT_REGISTERED'}
        if reasons:row['reasons']=sorted(reasons);blocked.append(row)
        else:ready.append(row)
    return {'ready':ready,'blocked':blocked,'external':external,'completed':done,'local_execution_closed':not ready and not blocked,'product_qualified':False}

def validate_catalog(root: Path) -> dict:
    tasks=load_tasks(root);pin=read_json(safe_path(root,'policy/baseline.json'));base=pin['root']
    req=read_json(safe_path(root,base+'/catalog/requirements.json'));tests=read_json(safe_path(root,base+'/catalog/acceptance-tests.json'));wps=read_json(safe_path(root,base+'/catalog/work-packages.json'));gates=read_json(safe_path(root,base+'/catalog/gates.json'))
    rids={r['id'] for r in req};tids={t['id'] for t in tests};wids={w['id'] for w in wps};gids={g['id'] for g in gates}
    cov=read_json(safe_path(root,'plan/coverage.json'))['requirements'];unmapped=sorted(rids-set(cov))
    if unmapped or set(cov)-rids: raise HarnessError('INVALID_PLAN','requirement coverage differs')
    owners={i:[] for i in rids}
    for t in tasks.values():
        if set(t['requirements'])-rids or set(t.get('related_requirements',[]))-rids or set(t['acceptance_ids'])-tids or set(t.get('work_packages',[]))-wids or set(t['qualification_depends_on'])-gids:
            raise HarnessError('INVALID_PLAN','unknown reference '+t['id'])
        for i in t['requirements']:owners[i].append(t['id'])
    for r in req:
        c=cov[r['id']]
        if owners[r['id']]!=[c['implementation']] or c['local_verification'] not in tasks or set(c['acceptance'])!=set(r['test_ids']) or c['qualification_gate']!=r['gate']:
            raise HarnessError('INVALID_PLAN','coverage mismatch '+r['id'])
        if not set(r['test_ids'])<=set(tasks[c['local_verification']]['acceptance_ids']):raise HarnessError('INVALID_PLAN','missing local acceptance')
    return {'requirements':len(rids),'unmapped':unmapped,'tasks':len(tasks),'work_packages':len(wids),'product_gates':len(gids)}
