"""P5 deterministic resource-aware scheduler.

P5 never changes the selected verification set. It schedules only the exact
campaign lane IDs supplied by P4/P3 and persists P2 receipts as workers finish.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .artifact_survival import budget_from_policy
from .common import HarnessError, clean_env, read_json, safe_path
from .test_orchestration import load_registry, estimate_entry_seconds, record_duration
from .verification_ledger import aggregate, resume_plan, run_campaign, write_receipt

_POLICY_REL='policy/resource-scheduler.json'


def _int_pos(value, field: str, *, maximum: int=10000) -> int:
    if isinstance(value,bool) or not isinstance(value,int) or value<1 or value>maximum:
        raise HarnessError('SCHEDULER_POLICY_INVALID',field)
    return value


def _number_pos(value, field: str) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or value<=0:
        raise HarnessError('SCHEDULER_POLICY_INVALID',field)
    return float(value)


def load_scheduler_policy(root: Path) -> dict:
    obj=read_json(safe_path(root,_POLICY_REL))
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('scheduler_mode')!='RESOURCE_SAFE_V1':
        raise HarnessError('SCHEDULER_POLICY_INVALID','header')
    out={
        'schema_version':1,'scheduler_mode':'RESOURCE_SAFE_V1',
        'max_workers':_int_pos(obj.get('max_workers'),'max_workers',maximum=128),
        'cpu_capacity_units':_int_pos(obj.get('cpu_capacity_units'),'cpu_capacity_units'),
        'memory_capacity_units':_int_pos(obj.get('memory_capacity_units'),'memory_capacity_units'),
        'io_capacity_units':_int_pos(obj.get('io_capacity_units'),'io_capacity_units'),
        'max_load_per_cpu':_number_pos(obj.get('max_load_per_cpu'),'max_load_per_cpu'),
        'min_free_memory_mb':_number_pos(obj.get('min_free_memory_mb'),'min_free_memory_mb'),
        'min_free_disk_mb':_number_pos(obj.get('min_free_disk_mb'),'min_free_disk_mb'),
        'preflight_failure_action':obj.get('preflight_failure_action'),
        'product_qualified':False,
    }
    patterns=obj.get('foreign_process_patterns')
    if not isinstance(patterns,list) or any(not isinstance(x,str) or not x for x in patterns) or len(patterns)!=len(set(patterns)):
        raise HarnessError('SCHEDULER_POLICY_INVALID','foreign_process_patterns')
    if out['preflight_failure_action']!='DRAIN_AND_PACKAGE':
        raise HarnessError('SCHEDULER_POLICY_INVALID','preflight_failure_action')
    out['foreign_process_patterns']=list(patterns)
    return out


def _entry_map(root: Path) -> dict[str,dict]:
    return {e['id']:e for e in load_registry(root)['entries']}


def _fits(entry: dict, cpu: int, mem: int, io_w: int, policy: dict) -> bool:
    return (cpu+entry['cpu_weight']<=policy['cpu_capacity_units'] and
            mem+entry['memory_weight']<=policy['memory_capacity_units'] and
            io_w+entry['io_weight']<=policy['io_capacity_units'])


def _validate_entry_capacity(entry: dict, policy: dict) -> None:
    if (entry['cpu_weight']>policy['cpu_capacity_units'] or
        entry['memory_weight']>policy['memory_capacity_units'] or
        entry['io_weight']>policy['io_capacity_units']):
        raise HarnessError('SCHEDULER_ENTRY_UNSCHEDULABLE',entry['id'])


def plan_waves(root: Path, entry_ids: list[str]) -> list[dict]:
    policy=load_scheduler_policy(root); entries=_entry_map(root)
    if len(entry_ids)!=len(set(entry_ids)):
        raise HarnessError('SCHEDULER_DUPLICATE_ENTRY')
    unknown=[x for x in entry_ids if x not in entries]
    if unknown: raise HarnessError('TEST_REGISTRY_UNKNOWN_ID',','.join(unknown))
    for eid in entry_ids:_validate_entry_capacity(entries[eid],policy)
    pending=list(entry_ids); waves=[]
    while pending:
        first=entries[pending[0]]
        if not first['parallel_safe']:
            wave_ids=[pending.pop(0)]
        else:
            wave_ids=[]; cpu=mem=io_w=0; exclusives=set(); used_indexes=[]
            # An unsafe entry is an ordering barrier. Safe entries before the barrier
            # may be packed if resource/exclusive constraints allow it.
            for idx,eid in enumerate(pending):
                e=entries[eid]
                if not e['parallel_safe']:
                    break
                ex=e['exclusive_resource']
                if ex is not None and ex in exclusives:
                    continue
                if len(wave_ids)>=policy['max_workers']:
                    break
                if not _fits(e,cpu,mem,io_w,policy):
                    continue
                wave_ids.append(eid); used_indexes.append(idx)
                cpu+=e['cpu_weight'];mem+=e['memory_weight'];io_w+=e['io_weight']
                if ex is not None:exclusives.add(ex)
            if not wave_ids:
                # The first item is safe and individually fits (validated above), so
                # this can only occur with an impossible policy/logic state.
                raise HarnessError('SCHEDULER_NO_PROGRESS',pending[0])
            for idx in reversed(used_indexes):pending.pop(idx)
        cpu=sum(entries[x]['cpu_weight'] for x in wave_ids)
        mem=sum(entries[x]['memory_weight'] for x in wave_ids)
        io_w=sum(entries[x]['io_weight'] for x in wave_ids)
        waves.append({'index':len(waves),'entry_ids':wave_ids,'cpu_weight':cpu,'memory_weight':mem,
                      'io_weight':io_w,'exclusive_resources':sorted({entries[x]['exclusive_resource'] for x in wave_ids if entries[x]['exclusive_resource'] is not None}),
                      'estimated_seconds':max(estimate_entry_seconds(root,x) for x in wave_ids)})
    return waves


def _read_mem_available_mb() -> float:
    path=Path('/proc/meminfo')
    if not path.is_file():raise OSError('meminfo unavailable')
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        if line.startswith('MemAvailable:'):
            return float(line.split()[1])/1024.0
    raise OSError('MemAvailable unavailable')


def _process_rows(patterns: list[str]) -> list[dict]:
    if not patterns:return []
    cp=subprocess.run(['ps','-eo','pid=,args='],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False,timeout=5)
    if cp.returncode!=0:raise OSError('ps failed')
    mine=os.getpid(); parent=os.getppid(); out=[]
    for line in cp.stdout.splitlines():
        line=line.strip()
        if not line:continue
        parts=line.split(None,1)
        if len(parts)!=2:continue
        try:pid=int(parts[0])
        except ValueError:continue
        command=parts[1]
        if pid in (mine,parent):continue
        if any(p in command for p in patterns):out.append({'pid':pid,'command':command})
    return out


def host_resource_snapshot(root: Path, policy: dict|None=None) -> dict:
    policy=policy or load_scheduler_policy(root)
    try:
        cpu=os.cpu_count() or 0
        load1=float(os.getloadavg()[0])
        mem=_read_mem_available_mb()
        disk=float(shutil.disk_usage(root).free)/(1024.0*1024.0)
        foreign=_process_rows(policy['foreign_process_patterns'])
    except (OSError,ValueError) as exc:
        return {'measurement_error':type(exc).__name__+':'+str(exc)}
    return {'cpu_count':cpu,'load1':load1,'available_memory_mb':mem,'free_disk_mb':disk,'foreign_processes':foreign}


def resource_preflight(root: Path, *, snapshot: dict|None=None) -> dict:
    policy=load_scheduler_policy(root); snap=dict(snapshot) if snapshot is not None else host_resource_snapshot(root,policy)
    base={'schema_version':1,'snapshot':snap,'product_qualified':False}
    required=('cpu_count','load1','available_memory_mb','free_disk_mb','foreign_processes')
    if any(k not in snap for k in required) or snap.get('measurement_error'):
        return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'RESOURCE_MEASUREMENT_FAILED'}
    try:
        cpu=float(snap['cpu_count']);load=float(snap['load1']);mem=float(snap['available_memory_mb']);disk=float(snap['free_disk_mb'])
    except (TypeError,ValueError):
        return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'RESOURCE_MEASUREMENT_FAILED'}
    if cpu<=0:return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'RESOURCE_MEASUREMENT_FAILED'}
    if load/cpu>policy['max_load_per_cpu']:
        return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'HIGH_LOAD'}
    if mem<policy['min_free_memory_mb']:
        return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'LOW_MEMORY'}
    if disk<policy['min_free_disk_mb']:
        return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'LOW_DISK'}
    foreign=snap['foreign_processes']
    if not isinstance(foreign,list):return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'RESOURCE_MEASUREMENT_FAILED'}
    if foreign:return {**base,'result':'BLOCKED','action':'DRAIN_AND_PACKAGE','reason':'FOREIGN_TEST_PROCESS'}
    return {**base,'result':'PASS','action':'START_WORK','reason':'RESOURCE_PREFLIGHT_PASS'}


def schedule_plan(root: Path, ledger: Path, campaign: dict, env_fp: str, remaining_seconds: float, *, preflight_snapshot: dict|None=None) -> dict:
    root=root.resolve(); ledger=ledger.resolve(); preflight=resource_preflight(root,snapshot=preflight_snapshot)
    lane_ids=[x['id'] for x in campaign['lanes']]
    if len(lane_ids)!=len(set(lane_ids)):raise HarnessError('LEDGER_CAMPAIGN_DUPLICATE_LANE')
    if preflight['action']!='START_WORK':
        return {'action':'DRAIN_AND_PACKAGE','reason':preflight['reason'],'preflight':preflight,
                'campaign_lane_ids':lane_ids,'reuse_lane_ids':[],'run_lane_ids':lane_ids,'waves':[],
                'product_qualified':False}
    resume=resume_plan(root,ledger,campaign,env_fp)
    waves=plan_waves(root,resume['run_lane_ids']) if resume['run_lane_ids'] else []
    scheduled_estimate=sum(w['estimated_seconds'] for w in waves)
    budget=budget_from_policy(root,remaining_seconds,scheduled_estimate)
    return {**budget,'preflight':preflight,'campaign_id':campaign['campaign_id'],'campaign_lane_ids':lane_ids,
            'reuse_lane_ids':list(resume['reuse_lane_ids']),'run_lane_ids':list(resume['run_lane_ids']),
            'resume_reasons':dict(resume['reasons']),'waves':waves,'scheduled_estimate_seconds':scheduled_estimate,
            'scheduler_mode':'RESOURCE_SAFE_V1','product_qualified':False}


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:return
    try:os.killpg(proc.pid,signal.SIGKILL)
    except (ProcessLookupError,PermissionError):
        try:proc.kill()
        except ProcessLookupError:pass


def _run_wave(root: Path, ledger: Path, campaign: dict, env_fp: str, wave: dict, entries: dict, usable_deadline: float, active_children: list[subprocess.Popen]|None=None) -> list[dict]:
    lane_map={x['id']:x for x in campaign['lanes']}; active={}; completed=[]
    run_dir=safe_path(root,'.harness/scheduler/'+campaign['campaign_id']+'/wave-'+str(wave['index']))
    run_dir.mkdir(parents=True,exist_ok=True)
    for eid in wave['entry_ids']:
        lane=lane_map[eid]; entry=entries[eid]; now=time.monotonic()
        if now>=usable_deadline:
            completed.append({'lane_id':eid,'status':'INCOMPLETE','started':False});continue
        out_path=run_dir/(eid+'.stdout');err_path=run_dir/(eid+'.stderr')
        out_f=out_path.open('wb');err_f=err_path.open('wb')
        started_wall=time.time();started_mono=time.monotonic()
        try:
            proc=subprocess.Popen(lane['argv'],cwd=root,env=clean_env(),stdout=out_f,stderr=err_f,start_new_session=True)
            if active_children is not None:active_children.append(proc)
            active[eid]={'proc':proc,'out_f':out_f,'err_f':err_f,'out_path':out_path,'err_path':err_path,
                         'started_wall':started_wall,'started_mono':started_mono,'lane':lane,'entry':entry}
        except OSError as exc:
            out_f.close();err_f.write(type(exc).__name__.encode());err_f.close()
            finished=time.time()
            write_receipt(root,ledger,campaign,lane,'ENVIRONMENT_BLOCKED',env_fp,started_at=started_wall,finished_at=finished,returncode=None,stdout=b'',stderr=type(exc).__name__.encode())
            completed.append({'lane_id':eid,'status':'ENVIRONMENT_BLOCKED','started':True})
    while active:
        now=time.monotonic()
        for eid,state in list(active.items()):
            proc=state['proc']; elapsed=now-state['started_mono']; lane=state['lane']; timed_out=elapsed>=float(lane['timeout_seconds']) or now>=usable_deadline
            rc=proc.poll()
            if rc is None and not timed_out:continue
            if rc is None:
                _kill_group(proc); proc.wait(timeout=5); status='TIMEOUT';rc=None
            else: status='PASS' if rc==0 else 'FAIL'
            state['out_f'].close();state['err_f'].close()
            out=state['out_path'].read_bytes() if state['out_path'].exists() else b''
            err=state['err_path'].read_bytes() if state['err_path'].exists() else b''
            finished=time.time()
            write_receipt(root,ledger,campaign,lane,status,env_fp,started_at=state['started_wall'],finished_at=finished,returncode=rc,stdout=out,stderr=err)
            if active_children is not None and proc in active_children:active_children.remove(proc)
            record_duration(root,eid,max(0.000001,time.monotonic()-state['started_mono']))
            completed.append({'lane_id':eid,'status':status,'started':True})
            del active[eid]
        if active:time.sleep(.01)
    return completed


def run_scheduled_campaign(root: Path, ledger: Path, campaign: dict, env_fp: str, remaining_seconds: float, *, preflight_snapshot: dict|None=None) -> dict:
    root=root.resolve();ledger=ledger.resolve();plan=schedule_plan(root,ledger,campaign,env_fp,remaining_seconds,preflight_snapshot=preflight_snapshot)
    if plan['action']!='START_WORK':
        return {**plan,'result':'INCOMPLETE','scheduler':{'reused_lane_ids':plan.get('reuse_lane_ids',[]),'completed_lane_ids':[],'waves_completed':0},'selected_scope_complete':False}
    entries=_entry_map(root); completed=[]; started=time.monotonic(); deadline=started+float(plan['usable_work_seconds'])
    # Preserve completed receipts if the coordinator is terminated gracefully.
    active_children=[]
    old_term=signal.getsignal(signal.SIGTERM)
    def _term(_signum,_frame):
        children=list(active_children)
        for p in children:_kill_group(p)
        for p in children:
            try:p.wait(timeout=2)
            except (subprocess.TimeoutExpired,ChildProcessError):pass
        raise SystemExit(143)
    try:
        if signal.getsignal(signal.SIGTERM) is not None:signal.signal(signal.SIGTERM,_term)
        for index,wave in enumerate(plan['waves']):
            if time.monotonic()+float(wave['estimated_seconds'])>deadline:
                return {**plan,'action':'DRAIN_AND_PACKAGE','reason':'RUNTIME_BUDGET_EXHAUSTED','result':'INCOMPLETE',
                        'scheduler':{'reused_lane_ids':plan['reuse_lane_ids'],'completed_lane_ids':[x['lane_id'] for x in completed],'waves_completed':index},'selected_scope_complete':False}
            # _run_wave owns child lifecycle and writes receipts before returning.
            rows=_run_wave(root,ledger,campaign,env_fp,wave,entries,deadline,active_children);completed.extend(rows)
            if any(x['status']!='PASS' for x in rows):
                break
    finally:
        try:signal.signal(signal.SIGTERM,old_term)
        except (ValueError,OSError):pass
    agg=aggregate(root,ledger,campaign,env_fp)
    completed_set={x['lane_id'] for x in completed if x.get('started')}
    campaign_order=[x['id'] for x in campaign['lanes']]
    agg['scheduler']={'reused_lane_ids':plan['reuse_lane_ids'],'completed_lane_ids':[x for x in campaign_order if x in completed_set],
                      'completion_order':[x['lane_id'] for x in completed if x.get('started')],
                      'waves_completed':sum(1 for w in plan['waves'] if all(any(r['lane_id']==eid for r in completed) for eid in w['entry_ids'])),
                      'planned_waves':plan['waves'],'preflight':plan['preflight'],'scheduled_estimate_seconds':plan['scheduled_estimate_seconds']}
    agg['selected_scope_complete']=agg['result']=='PASS'
    return agg


def measure_serial_vs_scheduled(root: Path, campaign: dict, env_fp: str, remaining_seconds: float, *, preflight_snapshot: dict|None=None) -> dict:
    base=Path(tempfile.mkdtemp(prefix='p5-measure-',dir=root.parent))
    serial_ledger=base/'serial';parallel_ledger=base/'scheduled'
    try:
        t0=time.monotonic();serial=run_campaign(root,serial_ledger,campaign,env_fp);serial_elapsed=time.monotonic()-t0
        t1=time.monotonic();scheduled=run_scheduled_campaign(root,parallel_ledger,campaign,env_fp,remaining_seconds,preflight_snapshot=preflight_snapshot);scheduled_elapsed=time.monotonic()-t1
        return {'schema_version':1,'serial_result':serial['result'],'scheduled_result':scheduled['result'],
                'selected_lane_ids':[x['id'] for x in campaign['lanes']],
                'serial_elapsed_seconds':serial_elapsed,'scheduled_elapsed_seconds':scheduled_elapsed,
                'speedup_ratio':serial_elapsed/scheduled_elapsed if scheduled_elapsed>0 else None,
                'measured':True,'product_qualified':False}
    finally:
        shutil.rmtree(base,ignore_errors=True)
