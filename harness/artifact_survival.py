"""Recoverable artifact candidates that survive later verification failure.

P1 deliberately keeps promotion conservative.  It creates deterministic source
archives without mutating the source tree and records verification state as
metadata rather than inferring it from ZIP success.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

from .common import HarnessError, canonical, clean_env, digest, file_hash, read_json
from .lifecycle import completion
from .packaging import payload_files
from .planner import load_tasks
from .snapshot import snapshot

_ALLOWED_STATUSES = {
    'UNVERIFIED',
    'PARTIAL',
    'VERIFIED',
    'FAILED_VERIFICATION',
    'ENVIRONMENT_BLOCKED',
}
_META_PREFIX = 'release/artifact-survival/'
_FIXED_TIME = (2026, 9, 12, 0, 0, 0)


def _git(root: Path, *args: str) -> str:
    try:
        p=subprocess.run(
            ['git',*args],cwd=root,env=clean_env(),text=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False,
        )
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise HarnessError('GIT_PROVENANCE_UNAVAILABLE',type(exc).__name__) from exc
    if p.returncode:
        raise HarnessError('GIT_PROVENANCE_UNAVAILABLE',p.stderr.strip()[:300])
    return p.stdout.strip()


def git_identity(root: Path) -> dict:
    head=_git(root,'rev-parse','HEAD')
    branch=_git(root,'branch','--show-current') or 'DETACHED'
    dirty=bool(_git(root,'status','--porcelain=v1','--untracked-files=all'))
    return {'head':head,'branch':branch,'dirty':dirty}


def _pending_tasks(root: Path) -> list[str]:
    tasks=load_tasks(root);done=completion(root)
    return sorted(tid for tid,t in tasks.items() if t.get('lane')!='EXTERNAL' and tid not in done)


def _verification_binding(root: Path, src: dict, git: dict, record_path: Path|None) -> dict:
    if record_path is None:
        raise HarnessError('VERIFICATION_RECORD_REQUIRED')
    if git['dirty']:
        raise HarnessError('VERIFICATION_DIRTY_SOURCE')
    record=read_json(record_path.resolve())
    if not isinstance(record,dict) or record.get('kind')!='HARNESS_PROMOTION_RECORD':
        raise HarnessError('VERIFICATION_PROMOTION_RECORD_REQUIRED')
    from .evidence_promotion import verify_promotion_record
    verified=verify_promotion_record(root,record_path.resolve())
    return {
        'state':'VERIFIED','pending_task_ids':[],
        'record_digest':verified['record_digest'],
        'record_scope':'FULL_CURRENT_TEST_REGISTRY',
        'promotion_contract':verified['promotion_contract'],
        'binding':verified['binding'],
        'promoted_from_candidate_sha256':verified['candidate']['sha256'],
    }


def _metadata(root: Path, status: str, next_step: str, reason: str|None,
              verification_record: Path|None=None) -> tuple[dict,dict,dict]:
    if status not in _ALLOWED_STATUSES:raise HarnessError('INVALID_ARTIFACT_STATUS',status)
    if not isinstance(next_step,str) or not next_step.strip() or len(next_step)>4000:
        raise HarnessError('INVALID_NEXT_ACTION')
    src=snapshot(root);git=git_identity(root)
    if status=='VERIFIED':
        verification=_verification_binding(root,src,git,verification_record)
    else:
        pending=_pending_tasks(root)
        state={
            'UNVERIFIED':'NOT_RUN',
            'PARTIAL':'INCOMPLETE',
            'FAILED_VERIFICATION':'FAILED',
            'ENVIRONMENT_BLOCKED':'ENVIRONMENT_BLOCKED',
        }[status]
        verification={
            'state':state,
            'pending_task_ids':pending,
            'record_digest':None,
            'promotion_contract':'P1_CONSERVATIVE_PROVISIONAL',
        }
    status_obj={
        'schema_version':1,
        'kind':'HARNESS_ARTIFACT_STATUS',
        'status':status,
        'source':{'algorithm':src['algorithm'],'digest':src['digest'],'file_count':len(src['files'])},
        'git':git,
        'verification':verification,
        'next_step':next_step.strip(),
        'reason':reason,
        'product_qualified':False,
        'nonclaims':['publisher authenticity','product readiness','independent security review'],
    }
    source_obj={
        'schema_version':1,
        'kind':'HARNESS_ARTIFACT_SOURCE',
        'source':status_obj['source'],
        'git':git,
    }
    return src,status_obj,source_obj


def _zip_info(name: str, mode: int=0o100644) -> zipfile.ZipInfo:
    info=zipfile.ZipInfo(name,date_time=_FIXED_TIME)
    info.compress_type=zipfile.ZIP_DEFLATED
    info.create_system=3
    info.external_attr=mode<<16
    return info


def _artifact_bytes(root: Path, status_obj: dict, source_obj: dict) -> dict[str,bytes]:
    return {
        _META_PREFIX+'STATUS.json': canonical(status_obj)+b'\n',
        _META_PREFIX+'SOURCE.json': canonical(source_obj)+b'\n',
        _META_PREFIX+'NEXT_STEP.md': ('# Next step\n\n'+status_obj['next_step']+'\n').encode('utf-8'),
    }


def create_artifact(root: Path, output: Path, status: str, next_step: str,
                    verification_record: Path|None=None, reason: str|None=None) -> dict:
    root=root.resolve();output=output.resolve()
    if output.is_relative_to(root):raise HarnessError('PACKAGE_OUTPUT_INVALID','write archive outside source root')
    # Reuse the established distribution boundary purely as a validator.  This
    # catches private names, symlinks, and case-fold collisions without writing
    # a distribution manifest into the source tree.
    payload_files(root)
    src,status_obj,source_obj=_metadata(root,status,next_step,reason,verification_record)
    meta=_artifact_bytes(root,status_obj,source_obj)
    source_paths=[row['path'] for row in src['files']]
    if any(p.startswith(_META_PREFIX) for p in source_paths):
        raise HarnessError('ARTIFACT_METADATA_COLLISION',_META_PREFIX)
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            prefix=root.name+'/'
            for rel in source_paths:
                p=root/rel
                mode=stat.S_IFREG | (p.stat().st_mode & 0o777)
                z.writestr(_zip_info(prefix+rel,mode),p.read_bytes())
            for rel,data in sorted(meta.items()):
                z.writestr(_zip_info(prefix+rel),data)
        with zipfile.ZipFile(output) as z:
            bad=z.testzip()
            if bad is not None:raise HarnessError('PACKAGE_ZIP_CORRUPT',bad)
            names=z.namelist()
            if len(names)!=len(set(names)):raise HarnessError('PACKAGE_DUPLICATE_ENTRY')
            for rel,data in meta.items():
                if z.read(root.name+'/'+rel)!=data:raise HarnessError('PACKAGE_READBACK_FAILED',rel)
    except HarnessError:
        raise
    except (OSError,zipfile.BadZipFile,RuntimeError) as exc:
        raise HarnessError('PACKAGE_WRITE_FAILED',type(exc).__name__) from exc
    sha=file_hash(output)
    output.with_name(output.name+'.sha256').write_text(sha+'  '+output.name+'\n',encoding='utf-8')
    return {
        'result':'PASS','status':status,'file':output.name,'size_bytes':output.stat().st_size,
        'sha256':sha,'source_digest':src['digest'],'git':status_obj['git'],
        'pending_verification':len(status_obj['verification']['pending_task_ids']),
        'product_qualified':False,
    }


def read_artifact_status(archive: Path) -> dict:
    try:
        with zipfile.ZipFile(archive) as z:
            matches=[n for n in z.namelist() if n.endswith('/'+_META_PREFIX+'STATUS.json')]
            if len(matches)!=1:raise HarnessError('PACKAGE_STATUS_MISSING_OR_DUPLICATE')
            return json.loads(z.read(matches[0]),object_pairs_hook=_reject_duplicate_pairs)
    except HarnessError:
        raise
    except (OSError,zipfile.BadZipFile,UnicodeError,ValueError) as exc:
        raise HarnessError('PACKAGE_STATUS_INVALID',type(exc).__name__) from exc


def _reject_duplicate_pairs(pairs: list[tuple[str,object]]) -> dict:
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('duplicate key')
        out[key]=value
    return out


def budget_decision(remaining_seconds: float, estimated_work_seconds: float,
                    packaging_reserve_seconds: float, checkpoint_reserve_seconds: float,
                    emergency_threshold_seconds: float) -> dict:
    values={
        'remaining_seconds':remaining_seconds,
        'estimated_work_seconds':estimated_work_seconds,
        'packaging_reserve_seconds':packaging_reserve_seconds,
        'checkpoint_reserve_seconds':checkpoint_reserve_seconds,
        'emergency_threshold_seconds':emergency_threshold_seconds,
    }
    for name,value in values.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0:
            raise HarnessError('INVALID_BUDGET',name)
    reserve=packaging_reserve_seconds+checkpoint_reserve_seconds
    usable=max(0,remaining_seconds-reserve)
    if usable<=emergency_threshold_seconds:
        action='DRAIN_AND_PACKAGE';reason='EMERGENCY_THRESHOLD'
    elif estimated_work_seconds>usable:
        action='DRAIN_AND_PACKAGE';reason='PACKAGING_RESERVE'
    else:
        action='START_WORK';reason='WITHIN_BUDGET'
    return {
        'action':action,
        'reason':reason,
        'remaining_seconds':remaining_seconds,
        'estimated_work_seconds':estimated_work_seconds,
        'reserve_seconds':reserve,
        'usable_work_seconds':usable,
        'emergency_threshold_seconds':emergency_threshold_seconds,
        'packaging_reserve_protected':True,
    }



def cycle_budget_decision(remaining_seconds: float, estimated_work_seconds: float,
                          checkpoint_reserve_seconds: float, emergency_threshold_seconds: float) -> dict:
    values={
        'remaining_seconds':remaining_seconds,
        'estimated_work_seconds':estimated_work_seconds,
        'checkpoint_reserve_seconds':checkpoint_reserve_seconds,
        'emergency_threshold_seconds':emergency_threshold_seconds,
    }
    for name,value in values.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0:
            raise HarnessError('INVALID_BUDGET',name)
    usable=max(0,remaining_seconds-checkpoint_reserve_seconds)
    if usable<=emergency_threshold_seconds:
        action='DRAIN_AND_CHECKPOINT';reason='EMERGENCY_THRESHOLD'
    elif estimated_work_seconds>usable:
        action='DRAIN_AND_CHECKPOINT';reason='CHECKPOINT_RESERVE'
    else:
        action='START_WORK';reason='WITHIN_BUDGET'
    return {
        'action':action,'reason':reason,'remaining_seconds':remaining_seconds,
        'estimated_work_seconds':estimated_work_seconds,'reserve_seconds':checkpoint_reserve_seconds,
        'usable_work_seconds':usable,'emergency_threshold_seconds':emergency_threshold_seconds,
        'checkpoint_reserve_protected':True,'packaging_reserve_protected':False,
        'packaging_required':False,'durability_mode':'GIT_CHECKPOINT_PRIMARY',
    }

def emergency_package(root: Path, output: Path, next_step: str, reason: str) -> dict:
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:
        raise HarnessError('INVALID_EMERGENCY_REASON')
    result=create_artifact(root,output,'PARTIAL',next_step,reason=reason.strip())
    result['emergency']=True
    result['reason']=reason.strip()
    return result


def load_policy(root: Path) -> dict:
    policy=read_json(root/'policy/artifact-survival.json')
    expected=['UNVERIFIED','PARTIAL','VERIFIED','FAILED_VERIFICATION','ENVIRONMENT_BLOCKED']
    if not isinstance(policy,dict) or policy.get('schema_version')!=1 or policy.get('statuses')!=expected:
        raise HarnessError('ARTIFACT_POLICY_INVALID')
    for key in ('default_packaging_reserve_seconds','default_checkpoint_reserve_seconds','default_emergency_threshold_seconds'):
        value=policy.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0:
            raise HarnessError('ARTIFACT_POLICY_INVALID',key)
    if policy.get('verified_inferred_from_package_success') is not False:
        raise HarnessError('ARTIFACT_POLICY_INVALID','verified_inferred_from_package_success')
    if policy.get('durability_mode','GIT_CHECKPOINT_PRIMARY')!='GIT_CHECKPOINT_PRIMARY':
        raise HarnessError('ARTIFACT_POLICY_INVALID','durability_mode')
    if policy.get('package_required_per_cycle',False) is not False:
        raise HarnessError('ARTIFACT_POLICY_INVALID','package_required_per_cycle')
    optional=policy.get('default_optional_packaging_reserve_seconds',0)
    if isinstance(optional,bool) or not isinstance(optional,(int,float)) or optional<0:
        raise HarnessError('ARTIFACT_POLICY_INVALID','default_optional_packaging_reserve_seconds')
    return policy


def budget_from_policy(root: Path, remaining_seconds: float, estimated_work_seconds: float,
                       packaging_reserve_seconds: float|None=None,
                       checkpoint_reserve_seconds: float|None=None,
                       emergency_threshold_seconds: float|None=None) -> dict:
    policy=load_policy(root)
    return budget_decision(
        remaining_seconds,estimated_work_seconds,
        policy['default_packaging_reserve_seconds'] if packaging_reserve_seconds is None else packaging_reserve_seconds,
        policy['default_checkpoint_reserve_seconds'] if checkpoint_reserve_seconds is None else checkpoint_reserve_seconds,
        policy['default_emergency_threshold_seconds'] if emergency_threshold_seconds is None else emergency_threshold_seconds,
    )


def cycle_budget_from_policy(root: Path, remaining_seconds: float, estimated_work_seconds: float,
                             checkpoint_reserve_seconds: float|None=None,
                             emergency_threshold_seconds: float|None=None) -> dict:
    policy=load_policy(root)
    return cycle_budget_decision(
        remaining_seconds,estimated_work_seconds,
        policy['default_checkpoint_reserve_seconds'] if checkpoint_reserve_seconds is None else checkpoint_reserve_seconds,
        policy['default_emergency_threshold_seconds'] if emergency_threshold_seconds is None else emergency_threshold_seconds,
    )
