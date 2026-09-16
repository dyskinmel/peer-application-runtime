"""Agent-neutral CLI. All commands are synchronous; no hidden model calls."""
from __future__ import annotations
import argparse
import json
import signal
import sys
from pathlib import Path
from .common import HarnessError, atomic_json, safe_path
from .doctor import probe
from .planner import select, validate_catalog
from .snapshot import snapshot, verify_baseline
from .context import build_context
from .lifecycle import begin, checkpoint, resume, completion, loop_state
from .execution import run_session, verify_run, recover_lock
from .artifact_survival import create_artifact, emergency_package, budget_from_policy, cycle_budget_from_policy
from .verification_ledger import load_campaign, resume_plan, run_campaign, aggregate
from .test_orchestration import load_registry, plan_tier, record_duration, run_tier
from .impact_selection import git_changed_paths, plan_impact, run_impact, select_impact, campaign_from_selection, write_campaign
from .resource_scheduler import resource_preflight, schedule_plan, run_scheduled_campaign
from .advanced_optimization import shard_plan, sample_plan, set_quarantine, observe_quarantine, quarantine_summary, cache_put, cache_get
from .evidence_promotion import write_promotion_record, verify_promotion_record
from .common import digest
from .native_readiness import native_resume


def main(argv: list[str]|None=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    s=p.add_subparsers(dest='command',required=True)
    for name in ('doctor','validate','next','status','native-resume'):s.add_parser(name)
    c=s.add_parser('context');c.add_argument('task');c.add_argument('--max-bytes',type=int,default=24000);c.add_argument('--text',action='store_true')
    c=s.add_parser('begin');c.add_argument('task')
    for name in ('run','loop'):c=s.add_parser(name);c.add_argument('session')
    c=s.add_parser('verify');c.add_argument('run')
    c=s.add_parser('checkpoint');c.add_argument('session');c.add_argument('--next',required=True)
    c=s.add_parser('resume');c.add_argument('checkpoint')
    c=s.add_parser('recover-lock');c.add_argument('--expected-token',required=True)
    c=s.add_parser('package');c.add_argument('--status',required=True,choices=['unverified','partial','verified','failed-verification','environment-blocked']);c.add_argument('--output',type=Path,required=True);c.add_argument('--next',required=True);c.add_argument('--verification-record',type=Path);c.add_argument('--reason')
    c=s.add_parser('emergency-package');c.add_argument('--output',type=Path,required=True);c.add_argument('--next',required=True);c.add_argument('--reason',required=True)
    c=s.add_parser('package-budget');c.add_argument('--remaining-seconds',type=float,required=True);c.add_argument('--estimated-work-seconds',type=float,required=True);c.add_argument('--packaging-reserve-seconds',type=float);c.add_argument('--checkpoint-reserve-seconds',type=float);c.add_argument('--emergency-threshold-seconds',type=float)
    c=s.add_parser('cycle-budget');c.add_argument('--remaining-seconds',type=float,required=True);c.add_argument('--estimated-work-seconds',type=float,required=True);c.add_argument('--checkpoint-reserve-seconds',type=float);c.add_argument('--emergency-threshold-seconds',type=float)
    for name in ('ledger-plan','ledger-run','ledger-aggregate'):
        c=s.add_parser(name);c.add_argument('--campaign',type=Path,required=True);c.add_argument('--ledger',type=Path)
    s.add_parser('resource-preflight')
    for name in ('schedule-plan','schedule-run'):
        c=s.add_parser(name);c.add_argument('--campaign',type=Path,required=True);c.add_argument('--ledger',type=Path);c.add_argument('--remaining-seconds',type=float,required=True)
    c=s.add_parser('test-plan');c.add_argument('--max-tier',choices=['S0','S1','S2','S3'],default=None);c.add_argument('--remaining-seconds',type=float,required=True)
    c=s.add_parser('test-duration-record');c.add_argument('--test-id',required=True);c.add_argument('--duration-seconds',type=float,required=True)
    c=s.add_parser('test-run');c.add_argument('--max-tier',choices=['S0','S1','S2','S3'],default=None);c.add_argument('--remaining-seconds',type=float,required=True)
    s.add_parser('test-registry')
    for name in ('impact-plan','impact-run','impact-schedule'):
        c=s.add_parser(name);c.add_argument('--remaining-seconds',type=float,required=True);c.add_argument('--changed-path',action='append',default=[]);c.add_argument('--base-ref');c.add_argument('--ledger',type=Path)
    c=s.add_parser('impact-campaign');c.add_argument('--output',type=Path,required=True);c.add_argument('--campaign-id',required=True);c.add_argument('--changed-path',action='append',default=[]);c.add_argument('--base-ref')
    c=s.add_parser('shard-plan');c.add_argument('--test-id',required=True);c.add_argument('--shards',type=int,required=True);c.add_argument('--campaign-id',required=True);c.add_argument('--output',type=Path)
    c=s.add_parser('sample-plan');c.add_argument('--item',action='append',required=True);c.add_argument('--seed',required=True);c.add_argument('--corpus-version',required=True);c.add_argument('--count',type=int,required=True)
    c=s.add_parser('quarantine-set');c.add_argument('--test-id',required=True);c.add_argument('--owner',required=True);c.add_argument('--expires-at',type=float,required=True);c.add_argument('--release-blocker',action='store_true');c.add_argument('--status',choices=['INVESTIGATING','QUARANTINED'],default='QUARANTINED')
    c=s.add_parser('quarantine-observe');c.add_argument('--test-id',required=True);c.add_argument('--failed',action='store_true')
    s.add_parser('quarantine-list')
    c=s.add_parser('promotion-review');c.add_argument('--candidate',type=Path,required=True);c.add_argument('--campaign',type=Path,required=True);c.add_argument('--ledger',type=Path,required=True);c.add_argument('--environment-fingerprint',required=True);c.add_argument('--output',type=Path,required=True);c.add_argument('--shard-plan',type=Path,action='append',default=[])
    c=s.add_parser('promotion-verify');c.add_argument('--record',type=Path,required=True);c.add_argument('--candidate',type=Path)
    for name in ('cache-put','cache-get'):
        c=s.add_parser(name);c.add_argument('--namespace',choices=['BUILD','FIXTURE'],required=True);c.add_argument('--key',required=True);c.add_argument('--definition-digest',required=True);c.add_argument('--fixture-digest',required=True);c.add_argument('--environment-fingerprint',required=True)
        if name=='cache-put':c.add_argument('--payload',type=Path,required=True)
    a=p.parse_args(argv);root=a.root.resolve()
    try:
        if a.command=='native-resume':out=native_resume(root)
        elif a.command=='doctor':
            out=probe(root=root);atomic_json(safe_path(root,'.harness/environment.json'),out)
        elif a.command=='validate':out={'result':'PASS','baseline':verify_baseline(root),'catalog':validate_catalog(root),'source_digest':snapshot(root)['digest'],'scope':'HARNESS_INPUT_INTEGRITY_ONLY'}
        elif a.command in ('next','status'):
            env=probe(root=root);done=completion(root,env);out=select(root,env['capabilities'],done)
            out.update(source_digest=snapshot(root)['digest'],product_gates={f'G{i}':'NOT_EVALUATED_BY_H0' for i in range(12)},qualification_engine='NOT_IMPLEMENTED_IN_H0')
        elif a.command=='context':
            out=build_context(root,a.task,a.max_bytes)
            if a.text:print(out['text']);return 0
        elif a.command=='begin':
            obj=begin(root,a.task);out={k:v for k,v in obj.items() if k not in ('source','environment')};out['source_digest']=obj['source']['digest'];out['environment_fingerprint']=obj['environment']['fingerprint']
        elif a.command=='run':
            obj=run_session(root,a.session);out={k:v for k,v in obj.items() if k not in ('source','environment')};out['source_digest']=obj['source']['digest']
        elif a.command=='verify':out=verify_run(root,a.run)
        elif a.command=='checkpoint':
            obj=checkpoint(root,a.session,a.next);out={k:v for k,v in obj.items() if k not in ('source','environment')};out['source_digest']=obj['source']['digest']
        elif a.command=='resume':out=resume(root,a.checkpoint)
        elif a.command=='recover-lock':out=recover_lock(root,a.expected_token)
        elif a.command=='package':
            status=a.status.replace('-','_').upper()
            out=create_artifact(root,a.output,status,a.next,a.verification_record,a.reason)
        elif a.command=='emergency-package':out=emergency_package(root,a.output,a.next,a.reason)
        elif a.command=='package-budget':
            out=budget_from_policy(root,a.remaining_seconds,a.estimated_work_seconds,a.packaging_reserve_seconds,a.checkpoint_reserve_seconds,a.emergency_threshold_seconds)
        elif a.command=='cycle-budget':
            out=cycle_budget_from_policy(root,a.remaining_seconds,a.estimated_work_seconds,a.checkpoint_reserve_seconds,a.emergency_threshold_seconds)
        elif a.command=='test-plan':out=plan_tier(root,a.max_tier,a.remaining_seconds)
        elif a.command=='test-duration-record':out=record_duration(root,a.test_id,a.duration_seconds)
        elif a.command=='test-run':out=run_tier(root,a.max_tier,a.remaining_seconds)
        elif a.command=='test-registry':out=load_registry(root)
        elif a.command=='resource-preflight':out=resource_preflight(root)
        elif a.command in ('schedule-plan','schedule-run'):
            from .doctor import probe as _sched_probe
            campaign=load_campaign(a.campaign.resolve())
            ledger=(a.ledger.resolve() if a.ledger else safe_path(root,'.harness/verification-ledger/'+campaign['campaign_id']))
            env_fp=_sched_probe(root=root)['fingerprint']
            if a.command=='schedule-plan':out=schedule_plan(root,ledger,campaign,env_fp,a.remaining_seconds)
            else:out=run_scheduled_campaign(root,ledger,campaign,env_fp,a.remaining_seconds)
        elif a.command in ('impact-plan','impact-run','impact-campaign','impact-schedule'):
            changed=list(a.changed_path or [])
            if a.base_ref or not changed:
                changed.extend(git_changed_paths(root,a.base_ref))
            changed=sorted(set(changed))
            if a.command=='impact-plan':out=plan_impact(root,changed,a.remaining_seconds)
            elif a.command=='impact-run':out=run_impact(root,changed,a.remaining_seconds)
            elif a.command=='impact-schedule':
                from .doctor import probe as _impact_sched_probe
                selection=select_impact(root,changed)
                cid='impact-'+digest({'changed_paths':changed,'selected_ids':selection['selected_ids']})[:16]
                campaign=campaign_from_selection(root,selection,cid)
                ledger=(a.ledger.resolve() if a.ledger else safe_path(root,'.harness/verification-ledger/'+cid))
                env_fp=_impact_sched_probe(root=root)['fingerprint']
                out=run_scheduled_campaign(root,ledger,campaign,env_fp,a.remaining_seconds);out['selection']=selection
            else:
                selection=select_impact(root,changed)
                campaign=campaign_from_selection(root,selection,a.campaign_id)
                out={**write_campaign(a.output,campaign),'selection':selection}
        elif a.command=='shard-plan':
            out=shard_plan(root,a.test_id,a.shards,a.campaign_id)
            if a.output:
                atomic_json(a.output.resolve(),out);out={**out,'output':str(a.output.resolve())}
        elif a.command=='sample-plan':out=sample_plan(list(a.item),a.seed,a.corpus_version,a.count)
        elif a.command=='quarantine-set':out=set_quarantine(root,a.test_id,a.owner,a.expires_at,a.release_blocker,status=a.status)
        elif a.command=='quarantine-observe':out=observe_quarantine(root,a.test_id,a.failed)
        elif a.command=='quarantine-list':out=quarantine_summary(root)
        elif a.command=='cache-put':out=cache_put(root,a.namespace,a.key,a.payload.resolve().read_bytes(),a.definition_digest,a.fixture_digest,a.environment_fingerprint)
        elif a.command=='cache-get':out=cache_get(root,a.namespace,a.key,a.definition_digest,a.fixture_digest,a.environment_fingerprint)
        elif a.command=='promotion-review':
            campaign=load_campaign(a.campaign.resolve()); shards=[read_json(p.resolve()) for p in a.shard_plan]
            out=write_promotion_record(root,a.output.resolve(),a.candidate.resolve(),campaign,a.ledger.resolve(),a.environment_fingerprint,shard_plans=shards)
        elif a.command=='promotion-verify':out=verify_promotion_record(root,a.record.resolve(),a.candidate.resolve() if a.candidate else None)
        elif a.command in ('ledger-plan','ledger-run','ledger-aggregate'):
            from .doctor import probe as _ledger_probe
            campaign=load_campaign(a.campaign.resolve())
            ledger=(a.ledger.resolve() if a.ledger else safe_path(root,'.harness/verification-ledger/'+campaign['campaign_id']))
            env_fp=_ledger_probe(root=root)['fingerprint']
            if a.command=='ledger-plan':out=resume_plan(root,ledger,campaign,env_fp)
            elif a.command=='ledger-run':out=run_campaign(root,ledger,campaign,env_fp)
            else:out=aggregate(root,ledger,campaign,env_fp)
        else:out=loop_state(root,a.session)
        print(json.dumps(out,ensure_ascii=False,indent=2))
        return 1 if out.get('valid') is False or out.get('status')=='FAIL' or out.get('state')=='BLOCKED' or out.get('result') in ('FAIL','FAIL_OR_INCOMPLETE') else 0
    except HarnessError as exc:
        print(json.dumps({'error':exc.code,'detail':exc.detail,'product_qualified':False},ensure_ascii=False,indent=2));return 2
    except KeyboardInterrupt:
        print(json.dumps({'error':'INTERRUPTED','product_qualified':False}));return 130
