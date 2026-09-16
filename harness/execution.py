"""Registered local checks with evidence-bound results. NOT an OS security sandbox."""
from __future__ import annotations
import contextlib
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from .common import HarnessError, atomic_json, clean_env, digest, file_hash, read_json, safe_path, valid_id
from .snapshot import snapshot, diff, allowed, guard_digest, excluded
from .planner import load_tasks
from .doctor import probe


def seal_record(path: Path, value: dict) -> None:
    value=dict(value);value.pop('integrity',None);value['integrity']=digest(value)
    atomic_json(path,value)


def read_record(path: Path) -> dict:
    value=read_json(path);unsigned=dict(value);seal=unsigned.pop('integrity',None)
    if seal!=digest(unsigned):raise HarnessError('RECORD_TAMPERED',path.name)
    return value


@contextlib.contextmanager
def workspace_lock(root: Path):
    path=safe_path(root,'.harness/writer.lock');path.parent.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:raise HarnessError('WORKSPACE_BUSY','Inspect lock; no automatic lock stealing.') from exc
    with os.fdopen(fd,'w') as f:
        import json
        json.dump({'pid':os.getpid(),'token':token,'created_ns':time.time_ns()},f);f.flush();os.fsync(f.fileno())
    try:yield
    finally:
        if path.exists() and read_json(path).get('token')==token:path.unlink()


def recover_lock(root: Path, expected_token: str) -> dict:
    path=safe_path(root,'.harness/writer.lock');rec=read_json(path)
    if rec.get('token')!=expected_token:raise HarnessError('LOCK_IDENTITY_CHANGED')
    pid=rec.get('pid')
    if type(pid)!=int or pid<=0:raise HarnessError('INVALID_LOCK')
    try:os.kill(pid,0)
    except ProcessLookupError:pass
    except (PermissionError,OSError) as exc:raise HarnessError('LOCK_OWNER_UNKNOWN',str(exc)) from exc
    else:raise HarnessError('LOCK_OWNER_ALIVE','PID reuse is conservatively treated as alive')
    if read_json(path)!=rec:raise HarnessError('LOCK_IDENTITY_CHANGED')
    path.unlink()
    return {'state':'LOCK_REMOVED','execution_replayed':False,'warning':'Inspect recorded child processes after abrupt host termination. No child is killed by this operation.'}


def definitions(root: Path, task: dict) -> list[dict]:
    registry=read_json(safe_path(root,'policy/checks.json'))['checks']
    ids=task['checks']
    if not ids or len(ids)!=len(set(ids)):raise HarnessError('CHECK_NOT_REGISTERED','empty/duplicate check set')
    defs=[]
    for cid in ids:
        valid_id(cid)
        if cid not in registry:raise HarnessError('CHECK_NOT_REGISTERED',cid)
        spec=dict(registry[cid]);argv=spec.get('argv',[])
        if len(argv)<2 or argv[0]!='{python}' or not argv[1].endswith('.py') or excluded(argv[1]):raise HarnessError('UNSAFE_COMMAND',cid)
        if not safe_path(root,argv[1]).is_file():raise HarnessError('CHECK_NOT_REGISTERED','missing executable script '+argv[1])
        # H0 intentionally admits Python script checks only. Add future runners through reviewed policy/code changes.
        if not all(isinstance(v,str) for v in argv):raise HarnessError('UNSAFE_COMMAND',cid)
        expected=spec.get('case_ids')
        if 'case_inventory' in spec:
            expected=read_json(safe_path(root,spec['case_inventory']))['case_ids']
        if not isinstance(expected,list) or not expected or any(not isinstance(x,str) or not x for x in expected) or len(set(expected))!=len(expected):raise HarnessError('CHECK_NOT_REGISTERED','invalid case inventory '+cid)
        timeout=spec.get('timeout_seconds',120)
        if type(timeout) not in (float,int) or not 0<timeout<=7200:raise HarnessError('UNSAFE_COMMAND','timeout '+cid)
        spec.update(id=cid,expected=sorted(expected));defs.append(spec)
    return defs


def case_errors(path: Path, expected: list[str], nonce: str) -> list[str]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2*1024*1024:return ['MISSING_OR_UNBOUNDED_RESULT']
        obj=read_json(path)
        if not isinstance(obj,dict):return ['MALFORMED_RESULT']
        if type(obj.get('schema_version')) is not int or obj['schema_version']!=1 or obj.get('nonce')!=nonce:return ['RESULT_BINDING_MISMATCH']
        cases=obj.get('cases')
        if not isinstance(cases,list):return ['MISSING_CASES']
        ids=[c['id'] for c in cases]
        if len(ids)!=len(set(ids)) or sorted(ids)!=sorted(expected):return ['CASE_IDENTITY_SET_MISMATCH']
        if any(c.get('status')!='PASS' for c in cases):return ['CASE_NOT_PASS']
        return []
    except (HarnessError,KeyError,TypeError,ValueError):return ['MALFORMED_RESULT']


def _stop_group(p: subprocess.Popen) -> None:
    if os.name=='posix':
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:p.wait(timeout=0.3)
        except subprocess.TimeoutExpired:pass
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    elif p.poll() is None:p.kill()
    try:p.wait(timeout=2)
    except subprocess.TimeoutExpired:pass


def _execute(root: Path, run_dir: Path, spec: dict, cap: int) -> dict:
    cid=spec['id'];nonce=secrets.token_hex(24);result=run_dir/(cid+'.result.json')
    env=clean_env();env.update(HARNESS_RESULT_PATH=str(result),HARNESS_NONCE=nonce)
    argv=[str(Path(sys.executable).resolve()),'-I','-S','-B',*spec['argv'][1:]]
    paths=[run_dir/(cid+'.stdout.log'),run_dir/(cid+'.stderr.log')]
    count=[0];mu=threading.Lock();exceeded=threading.Event();reader_error=threading.Event()
    def drain(pipe,path):
        try:
            with path.open('wb') as f:
                while True:
                    buf=pipe.read(4096)
                    if not buf:break
                    with mu:
                        room=max(0,cap-count[0]);accepted=buf[:room];count[0]+=len(accepted)
                        if len(buf)>room:exceeded.set()
                    f.write(accepted)
                f.flush();os.fsync(f.fileno())
        except (OSError,ValueError):reader_error.set()
        finally:pipe.close()
    start=time.monotonic();status='PASS';errors=[];p=None
    try:
        p=subprocess.Popen(argv,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=os.name=='posix',close_fds=True)
        threads=[threading.Thread(target=drain,args=(pipe,path),daemon=True) for pipe,path in zip((p.stdout,p.stderr),paths)]
        for t in threads:t.start()
        while p.poll() is None:
            if exceeded.is_set():status='LOG_LIMIT';break
            if time.monotonic()-start>spec['timeout_seconds']:status='TIMEOUT';break
            time.sleep(0.01)
        _stop_group(p)
        for t in threads:t.join(timeout=2)
        if any(t.is_alive() for t in threads) or reader_error.is_set():status='INCOMPLETE_LOG'
        if exceeded.is_set():status='LOG_LIMIT'
        code=p.returncode
        if code!=0:errors.append('NONZERO_EXIT')
        errors+=case_errors(result,spec['expected'],nonce)
        if errors and status=='PASS':status='FAIL'
    except (KeyboardInterrupt,SystemExit):
        if p:_stop_group(p)
        status='INTERRUPTED';code=None;errors=['CHECK_INTERRUPTED']
    except OSError as exc:
        status='FAIL';code=None;errors=['SPAWN_FAILED:'+type(exc).__name__]
    artifacts={}
    for path in paths+[result]:
        if path.exists() and not path.is_symlink():artifacts[path.name]={'sha256':file_hash(path),'size':path.stat().st_size}
    return {'id':cid,'argv':spec['argv'],'executed_argv':argv,'definition_digest':digest(spec),'expected':spec['expected'],'nonce':nonce,'status':status,'returncode':code,'elapsed_seconds':round(time.monotonic()-start,6),'artifacts':artifacts,'errors':errors}


def repeated_failure(root: Path, session: dict, current: dict|None=None) -> bool:
    """Two identical failures on unchanged input are a stop signal, not a retry prompt."""
    if len(session['attempts'])<2:return False
    try:
        rs=[read_record(safe_path(root,'.harness/runs/'+r+'/receipt.json')) for r in session['attempts'][-2:]]
        now=current if current is not None else snapshot(root)
        if any(r['status']!='FAIL' or r['source']['digest']!=now['digest'] for r in rs):return False
        def signature(r):return digest({'errors':r['errors'],'checks':[(c['id'],c['status'],c['errors']) for c in r['checks']]})
        return signature(rs[0])==signature(rs[1])
    except (HarnessError,KeyError,TypeError):return False


def run_session(root: Path, session_id: str) -> dict:
    valid_id(session_id);session_path=safe_path(root,f'.harness/sessions/{session_id}.json')
    with workspace_lock(root):
        s=read_record(session_path);task=load_tasks(root).get(s['task_id'])
        if not task:raise HarnessError('UNKNOWN_TASK')
        if guard_digest(root)!=s['guard_digest']:raise HarnessError('GUARD_CHANGED')
        candidate=snapshot(root);changed=diff(s['source'],candidate)
        outside=[p for p in changed if not allowed(p,task['allowed_paths'])]
        if outside:raise HarnessError('SCOPE_VIOLATION',','.join(outside))
        env=probe(task['required_capabilities'],root=root)
        if env['fingerprint']!=s['environment']['fingerprint']:raise HarnessError('ENVIRONMENT_CHANGED')
        policy=read_json(safe_path(root,'policy/runtime.json'))
        if len(s['attempts'])>=min(task.get('max_attempts',3),policy['max_attempts']):raise HarnessError('ATTEMPT_BUDGET')
        age=(time.time_ns()-s['created_ns'])/1e9
        if age<0:raise HarnessError('CLOCK_ROLLBACK')
        if age>policy['max_session_seconds']:raise HarnessError('SESSION_EXPIRED')
        if repeated_failure(root,s,candidate):raise HarnessError('NO_PROGRESS')
        defs=definitions(root,task)
        rid='run-'+uuid.uuid4().hex;run_dir=safe_path(root,'.harness/runs/'+rid);run_dir.mkdir(parents=True)
        # Journal attempt before dispatch; a torn run cannot look like a successful run.
        s['attempts'].append(rid);s['state']='VERIFYING';seal_record(session_path,s)
        start={'id':rid,'task_id':task['id'],'session_id':session_id,'source':candidate,'guard_digest':s['guard_digest'],'task_digest':digest(task),'environment':env,'check_ids':[d['id'] for d in defs],'created_ns':time.time_ns()}
        seal_record(run_dir/'started.json',start)
        results=[];errors=[]
        for spec in defs:
            results.append(_execute(root,run_dir,spec,policy['max_log_bytes']))
            if snapshot(root)['digest']!=candidate['digest']:
                errors.append('SOURCE_CHANGED_DURING_RUN');break
            if results[-1]['status']=='INTERRUPTED':break
        final=snapshot(root)
        if final['digest']!=candidate['digest'] and 'SOURCE_CHANGED_DURING_RUN' not in errors:errors.append('SOURCE_CHANGED_DURING_RUN')
        good=len(results)==len(defs) and all(x['status']=='PASS' for x in results) and not errors
        rec={**start,'schema_version':1,'checks':results,'status':'PASS' if good else 'FAIL','errors':errors,'completed_ns':time.time_ns(),'source_after_digest':final['digest'],'assurance':'LOCAL_HONEST_EXECUTION; NOT A HOSTILE-SAME-USER ATTESTATION'}
        seal_record(run_dir/'receipt.json',rec)
        s['state']='CANDIDATE_VERIFIED' if good else 'NEEDS_WORK';s['last_run']=rid;seal_record(session_path,s)
        return read_record(run_dir/'receipt.json')


def verify_run(root: Path, run_id: str, environment: dict|None=None, current: dict|None=None) -> dict:
    valid_id(run_id);errors=[]
    try:
        run_dir=safe_path(root,'.harness/runs/'+run_id);r=read_record(run_dir/'receipt.json');start=read_record(run_dir/'started.json')
        tasks=load_tasks(root);t=tasks.get(r['task_id'])
        if not t:raise HarnessError('UNKNOWN_TASK')
        if r['id']!=run_id or r['session_id']!=start['session_id'] or r['source']!=start['source'] or r['task_digest']!=start['task_digest']:errors.append('START_BINDING_MISMATCH')
        if r['status']!='PASS' or r.get('errors'):errors.append('RUN_NOT_PASS')
        now=current if current is not None else snapshot(root)
        if r['source']['digest']!=now['digest'] or r['source_after_digest']!=now['digest']:errors.append('SOURCE_STALE')
        if r['guard_digest']!=guard_digest(root) or r['task_digest']!=digest(t):errors.append('CONTRACT_CHANGED')
        env=environment if environment is not None else probe(t['required_capabilities'],root=root)
        if r['environment']!=start['environment'] or r['environment']['fingerprint']!=env['fingerprint']:errors.append('ENVIRONMENT_CHANGED')
        defs=definitions(root,t);ids=[c['id'] for c in r['checks']];expected=[x['id'] for x in defs]
        if ids!=expected or r['check_ids']!=expected or start['check_ids']!=expected:errors.append('CHECK_SET_MISMATCH')
        byid={x['id']:x for x in defs}
        for c in r['checks']:
            spec=byid.get(c['id'])
            if not spec or c['definition_digest']!=digest(spec):errors.append('CHECK_DEFINITION_CHANGED');continue
            if c['status']!='PASS' or c['returncode']!=0 or c['errors']:errors.append('CHECK_NOT_PASS')
            names=[c['id']+suffix for suffix in ('.stdout.log','.stderr.log','.result.json')]
            if set(c['artifacts'])!=set(names):errors.append('ARTIFACT_SET_MISMATCH')
            for name in names:
                p=safe_path(root,f'.harness/runs/{run_id}/{name}');old=c['artifacts'].get(name)
                if not p.is_file() or old!={'sha256':file_hash(p),'size':p.stat().st_size}:errors.append('ARTIFACT_CHANGED:'+name)
            errors+=case_errors(run_dir/(c['id']+'.result.json'),spec['expected'],c['nonce'])
        return {'id':run_id,'task_id':r['task_id'],'valid':not errors,'errors':sorted(set(errors)),'product_qualified':False}
    except (HarnessError,KeyError,TypeError,ValueError,OSError) as exc:
        return {'id':run_id,'valid':False,'errors':[getattr(exc,'code',type(exc).__name__)],'product_qualified':False}
