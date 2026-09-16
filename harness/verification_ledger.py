"""Resumable, fail-closed lane verification receipts.

P2 stores one sealed receipt per lane under .harness so completed evidence
survives coordinator/session termination without changing the source digest.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

from .common import HarnessError, atomic_json, canonical, clean_env, digest, read_json, valid_id
from .snapshot import snapshot

STATUSES = ('PASS','FAIL','TIMEOUT','INCOMPLETE','ENVIRONMENT_BLOCKED','NOT_RUN')
TIERS = ('S0','S1','S2','S3')


def _campaign_core(campaign: dict) -> dict:
    return {'schema_version':1,'campaign_id':campaign['campaign_id'],'lanes':campaign['lanes']}


def lane_definition_digest(lane: dict) -> str:
    core={
        'id':lane['id'],
        'argv':lane['argv'],
        'case_ids':lane['case_ids'],
        'timeout_seconds':lane['timeout_seconds'],
        'tier':lane.get('tier','S2'),
    }
    return digest(core)


def campaign_digest(campaign: dict) -> str:
    return digest(_campaign_core(campaign))


def load_campaign(path: Path) -> dict:
    obj=read_json(path)
    if not isinstance(obj,dict) or obj.get('schema_version')!=1:
        raise HarnessError('LEDGER_CAMPAIGN_INVALID')
    cid=valid_id(obj.get('campaign_id'))
    lanes=obj.get('lanes')
    if not isinstance(lanes,list) or not lanes:
        raise HarnessError('LEDGER_CAMPAIGN_INVALID','lanes')
    seen=set(); cleaned=[]
    for raw in lanes:
        if not isinstance(raw,dict):raise HarnessError('LEDGER_CAMPAIGN_INVALID','lane')
        lid=valid_id(raw.get('id'))
        if lid in seen:raise HarnessError('LEDGER_CAMPAIGN_DUPLICATE_LANE',lid)
        seen.add(lid)
        argv=raw.get('argv'); cases=raw.get('case_ids'); timeout=raw.get('timeout_seconds'); tier=raw.get('tier','S2')
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) or not x for x in argv):
            raise HarnessError('LEDGER_CAMPAIGN_INVALID',lid+':argv')
        if not isinstance(cases,list) or not cases or any(not isinstance(x,str) or not x for x in cases) or len(cases)!=len(set(cases)):
            raise HarnessError('LEDGER_CAMPAIGN_INVALID',lid+':case_ids')
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or timeout<=0:
            raise HarnessError('LEDGER_CAMPAIGN_INVALID',lid+':timeout')
        if tier not in TIERS: raise HarnessError('LEDGER_CAMPAIGN_INVALID',lid+':tier')
        cleaned.append({'id':lid,'argv':argv,'case_ids':cases,'timeout_seconds':timeout,'tier':tier})
    return {'schema_version':1,'campaign_id':cid,'lanes':cleaned}


def _receipt_body(root: Path, campaign: dict, lane: dict, status: str, env_fp: str,
                  *, started_at: float, finished_at: float, returncode: int|None,
                  stdout: bytes=b'', stderr: bytes=b'') -> dict:
    if status not in STATUSES:raise HarnessError('LEDGER_STATUS_INVALID',status)
    if not isinstance(env_fp,str) or not env_fp:raise HarnessError('LEDGER_ENVIRONMENT_INVALID')
    if finished_at < started_at:raise HarnessError('LEDGER_TIMING_INVALID')
    src=snapshot(root)
    return {
        'schema_version':1,
        'kind':'HARNESS_LANE_RECEIPT',
        'campaign_id':campaign['campaign_id'],
        'campaign_digest':campaign_digest(campaign),
        'lane_id':lane['id'],
        'lane_definition_digest':lane_definition_digest(lane),
        'source_digest':src['digest'],
        'environment_fingerprint':env_fp,
        'status':status,
        'tier':lane.get('tier','S2'),
        'started_at':started_at,
        'finished_at':finished_at,
        'duration_seconds':max(0.0,finished_at-started_at),
        'returncode':returncode,
        'stdout':{'bytes':len(stdout),'sha256':hashlib.sha256(stdout).hexdigest()},
        'stderr':{'bytes':len(stderr),'sha256':hashlib.sha256(stderr).hexdigest()},
        'product_qualified':False,
    }


def _seal(body: dict) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def write_receipt(root: Path, ledger: Path, campaign: dict, lane: dict, status: str, env_fp: str,
                  *, started_at: float, finished_at: float, returncode: int|None,
                  stdout: bytes=b'', stderr: bytes=b'') -> Path:
    root=root.resolve(); ledger=ledger.resolve()
    body=_receipt_body(root,campaign,lane,status,env_fp,started_at=started_at,finished_at=finished_at,
                       returncode=returncode,stdout=stdout,stderr=stderr)
    obj=dict(body);obj['seal_sha256']=_seal(body)
    receipts=ledger/'receipts';receipts.mkdir(parents=True,exist_ok=True)
    path=receipts/(lane['id']+'.json')
    atomic_json(path,obj)
    return path


def _load_sealed(path: Path) -> dict:
    obj=read_json(path)
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or obj.get('kind')!='HARNESS_LANE_RECEIPT':
        raise HarnessError('LEDGER_RECEIPT_INVALID',path.name)
    seal=obj.get('seal_sha256')
    body={k:v for k,v in obj.items() if k!='seal_sha256'}
    if not isinstance(seal,str) or seal!=_seal(body):
        raise HarnessError('LEDGER_RECEIPT_TAMPERED',path.name)
    return obj


def verify_receipt(root: Path, path: Path, campaign: dict, lane: dict, env_fp: str) -> dict:
    obj=_load_sealed(path)
    if obj.get('campaign_id')!=campaign['campaign_id'] or obj.get('lane_id')!=lane['id']:
        raise HarnessError('LEDGER_RECEIPT_ID_MISMATCH',path.name)
    if obj.get('lane_definition_digest')!=lane_definition_digest(lane):
        raise HarnessError('LEDGER_TEST_DEFINITION_STALE',lane['id'])
    if obj.get('source_digest')!=snapshot(root)['digest']:
        raise HarnessError('LEDGER_SOURCE_STALE',lane['id'])
    if obj.get('environment_fingerprint')!=env_fp:
        raise HarnessError('LEDGER_ENVIRONMENT_STALE',lane['id'])
    if obj.get('status') not in STATUSES:
        raise HarnessError('LEDGER_RECEIPT_INVALID',lane['id']+':status')
    return obj


def _receipt_index(ledger: Path) -> dict[str,list[Path]]:
    out={}
    d=ledger.resolve()/'receipts'
    if not d.exists():return out
    for p in sorted(d.glob('*.json')):
        obj=_load_sealed(p)
        lid=obj.get('lane_id')
        if not isinstance(lid,str):raise HarnessError('LEDGER_RECEIPT_INVALID',p.name)
        out.setdefault(lid,[]).append(p)
    return out


def aggregate(root: Path, ledger: Path, campaign: dict, env_fp: str) -> dict:
    idx=_receipt_index(ledger); expected={x['id']:x for x in campaign['lanes']}
    extras=sorted(set(idx)-set(expected))
    if extras:raise HarnessError('LEDGER_UNEXPECTED_LANE',','.join(extras))
    dup=sorted(k for k,v in idx.items() if len(v)!=1)
    if dup:raise HarnessError('LEDGER_DUPLICATE_LANE',','.join(dup))
    missing=sorted(set(expected)-set(idx)); statuses={}
    for lid,lane in expected.items():
        if lid in idx:
            obj=verify_receipt(root,idx[lid][0],campaign,lane,env_fp)
            statuses[lid]=obj['status']
    if missing:
        return {'result':'INCOMPLETE','campaign_id':campaign['campaign_id'],'missing_lane_ids':missing,
                'lane_statuses':statuses,'pass_count':sum(v=='PASS' for v in statuses.values()),
                'expected_count':len(expected),'product_qualified':False}
    result='PASS' if all(v=='PASS' for v in statuses.values()) else 'FAIL_OR_INCOMPLETE'
    return {'result':result,'campaign_id':campaign['campaign_id'],'missing_lane_ids':[],
            'lane_statuses':statuses,'pass_count':sum(v=='PASS' for v in statuses.values()),
            'expected_count':len(expected),'product_qualified':False}


def resume_plan(root: Path, ledger: Path, campaign: dict, env_fp: str) -> dict:
    idx=_receipt_index(ledger); expected={x['id']:x for x in campaign['lanes']}
    dup=sorted(k for k,v in idx.items() if len(v)!=1)
    if dup:raise HarnessError('LEDGER_DUPLICATE_LANE',','.join(dup))
    reuse=[];run=[];reasons={}
    for lid,lane in expected.items():
        paths=idx.get(lid,[])
        if not paths:
            run.append(lid);reasons[lid]='LEDGER_RECEIPT_MISSING';continue
        try:obj=verify_receipt(root,paths[0],campaign,lane,env_fp)
        except HarnessError as exc:
            if exc.code=='LEDGER_RECEIPT_TAMPERED':raise
            run.append(lid);reasons[lid]=exc.code;continue
        if obj['status']=='PASS':reuse.append(lid)
        else:run.append(lid);reasons[lid]='STATUS_'+obj['status']
    return {'campaign_id':campaign['campaign_id'],'reuse_lane_ids':reuse,'run_lane_ids':run,
            'reasons':reasons,'product_qualified':False}


def run_campaign(root: Path, ledger: Path, campaign: dict, env_fp: str) -> dict:
    root=root.resolve();plan=resume_plan(root,ledger,campaign,env_fp)
    lane_map={x['id']:x for x in campaign['lanes']}
    for lid in plan['run_lane_ids']:
        lane=lane_map[lid];started=time.time();out=b'';err=b'';rc=None
        try:
            cp=subprocess.run(lane['argv'],cwd=root,env=clean_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=lane['timeout_seconds'],check=False,start_new_session=True)
            out=cp.stdout;err=cp.stderr;rc=cp.returncode;status='PASS' if rc==0 else 'FAIL'
        except subprocess.TimeoutExpired as exc:
            out=exc.stdout or b'';err=exc.stderr or b'';status='TIMEOUT'
        except OSError as exc:
            err=type(exc).__name__.encode();status='ENVIRONMENT_BLOCKED'
        finished=time.time()
        write_receipt(root,ledger,campaign,lane,status,env_fp,started_at=started,finished_at=finished,
                      returncode=rc,stdout=out,stderr=err)
    return aggregate(root,ledger,campaign,env_fp)
