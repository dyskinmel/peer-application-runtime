"""Bounded sessions, verified completion, and non-replaying checkpoints."""
from __future__ import annotations
import time
import uuid
from pathlib import Path
from .common import HarnessError, digest, safe_path, valid_id
from .snapshot import snapshot, guard_digest, diff, allowed
from .doctor import probe
from .planner import load_tasks, select
from .execution import read_record, seal_record, verify_run, workspace_lock, repeated_failure


def completion(root: Path, environment: dict|None=None) -> dict:
    now=snapshot(root);done={}
    runs=safe_path(root,'.harness/runs')
    if not runs.exists():return done
    for d in sorted(runs.iterdir()):
        if d.is_symlink():raise HarnessError('UNSAFE_PATH','run symlink')
        if not d.is_dir():continue
        v=verify_run(root,d.name,current=now)
        if v['valid']:done[v['task_id']]=v['id']
    return done


def begin(root: Path, task_id: str) -> dict:
    tasks=load_tasks(root)
    if task_id not in tasks:raise HarnessError('UNKNOWN_TASK',task_id)
    t=tasks[task_id]
    if t['lane']=='EXTERNAL':raise HarnessError('EXTERNAL_OPERATOR_REQUIRED','External qualification is not dispatched by H0.')
    env=probe(t['required_capabilities'],root=root);done=completion(root)
    missing=[d for d in set(t['implementation_depends_on']+t['verification_depends_on']) if d not in done]
    if missing:raise HarnessError('DEPENDENCY_NOT_VERIFIED',','.join(sorted(missing)))
    missing=[c for c in t['required_capabilities'] if not env['capabilities'].get(c)]
    if missing:raise HarnessError('CAPABILITY_MISSING',','.join(missing))
    sid='session-'+uuid.uuid4().hex
    s={'schema_version':1,'id':sid,'task_id':task_id,'task_digest':digest(t),'created_ns':time.time_ns(),'source':snapshot(root),'guard_digest':guard_digest(root),'environment':env,'state':'ACTIVE','attempts':[],'last_run':None}
    seal_record(safe_path(root,'.harness/sessions/'+sid+'.json'),s)
    return read_record(safe_path(root,'.harness/sessions/'+sid+'.json'))


def checkpoint(root: Path, session_id: str, next_action: str) -> dict:
    valid_id(session_id)
    if not next_action.strip() or len(next_action)>4000:raise HarnessError('INVALID_NEXT_ACTION')
    with workspace_lock(root):
        s=read_record(safe_path(root,f'.harness/sessions/{session_id}.json'));t=load_tasks(root)[s['task_id']]
        if guard_digest(root)!=s['guard_digest']:raise HarnessError('GUARD_CHANGED')
        now=snapshot(root);changed=diff(s['source'],now)
        if any(not allowed(p,t['allowed_paths']) for p in changed):raise HarnessError('SCOPE_VIOLATION')
        cid='checkpoint-'+uuid.uuid4().hex
        c={'schema_version':1,'id':cid,'session_id':session_id,'task_id':s['task_id'],'source':now,'guard_digest':guard_digest(root),'environment':probe(t['required_capabilities'],root=root),'session_digest':digest(s),'next_action':next_action,'run_ids':list(s['attempts']),'created_ns':time.time_ns(),'product_gates':'NOT_PROMOTED','execution_replayed':False}
        seal_record(safe_path(root,'.harness/checkpoints/'+cid+'.json'),c)
        return read_record(safe_path(root,'.harness/checkpoints/'+cid+'.json'))


def resume(root: Path, checkpoint_id: str) -> dict:
    valid_id(checkpoint_id);errors=[]
    try:
        c=read_record(safe_path(root,'.harness/checkpoints/'+checkpoint_id+'.json'));s=read_record(safe_path(root,'.harness/sessions/'+c['session_id']+'.json'))
        if c['source']['digest']!=snapshot(root)['digest']:errors.append('SOURCE_STALE')
        if c['guard_digest']!=guard_digest(root):errors.append('GUARD_CHANGED')
        if c['environment']['fingerprint']!=probe(c['environment']['scope'],root=root)['fingerprint']:errors.append('ENVIRONMENT_CHANGED')
        if c['session_digest']!=digest(s):errors.append('SESSION_ADVANCED')
        if safe_path(root,'.harness/writer.lock').exists():errors.append('WORKSPACE_LOCK_PRESENT')
        v=[verify_run(root,r) for r in c['run_ids']]
        # Failed/incomplete prior attempts are work history, never completion; their results are shown explicitly.
        return {'id':checkpoint_id,'state':'BLOCKED' if errors else 'READY','errors':errors,'session_id':c['session_id'],'task_id':c['task_id'],'next_action':c['next_action'],'previous_runs':v,'execution_replayed':False}
    except (HarnessError,KeyError,TypeError,OSError) as exc:return {'id':checkpoint_id,'state':'BLOCKED','errors':[getattr(exc,'code',type(exc).__name__)],'execution_replayed':False}


def loop_state(root: Path, session_id: str) -> dict:
    s=read_record(safe_path(root,f'.harness/sessions/{valid_id(session_id)}.json'));t=load_tasks(root)[s['task_id']]
    if guard_digest(root)!=s['guard_digest']:return {'action':'STOP','reason':'GUARD_CHANGED'}
    if s.get('last_run'):
        v=verify_run(root,s['last_run'])
        if v['valid']:return {'action':'CHECKPOINT_AND_REVIEW','reason':'VERIFIED_LOCAL_TASK','run_id':v['id'],'product_qualified':False}
    if repeated_failure(root,s):return {'action':'STOP','reason':'NO_PROGRESS'}
    if len(s['attempts'])>=t.get('max_attempts',3):return {'action':'STOP','reason':'ATTEMPT_BUDGET'}
    return {'action':'IMPLEMENT_AND_VERIFY','task_id':s['task_id'],'remaining_attempts':t.get('max_attempts',3)-len(s['attempts']),'checks_registered':bool(t['checks']),'no_background_execution':True}
