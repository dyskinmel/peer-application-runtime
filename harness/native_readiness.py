"""Native handoff readiness without promoting native or production qualification."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path
from .artifact_survival import git_identity
from .common import clean_env, file_hash
from .doctor import probe
from .planner import validate_catalog
from .snapshot import snapshot, verify_baseline


def _git(root: Path, *args: str) -> str:
    cp=subprocess.run(['git',*args],cwd=root,env=clean_env(),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    return cp.stdout.strip() if cp.returncode==0 else ''


def _digest_file(root: Path, rel: str) -> str|None:
    p=root/rel
    return file_hash(p) if p.is_file() else None


def _contract_integrity(root: Path) -> dict:
    errors=[]
    for name in ('g0-actor','g0-wire','g0-store'):
        cp=root/'handoff/native_readiness/contracts'/f'{name}.json'
        rp=root/'handoff/native_readiness/corpora'/f'{name}.json'
        try:
            contract=json.loads(cp.read_text()); corpus=json.loads(rp.read_text())
        except Exception as exc:
            errors.append(f'{name}:LOAD:{type(exc).__name__}'); continue
        if contract.get('product_qualified') is not False or corpus.get('product_qualified') is not False:
            errors.append(f'{name}:PROMOTION')
        for row in corpus.get('bindings',[]):
            p=root/row.get('path','')
            if not p.is_file() or file_hash(p)!=row.get('sha256'): errors.append(f"{name}:HASH:{row.get('path')}")
    return {'result':'PASS' if not errors else 'FAIL','errors':errors}


def native_resume(root: Path) -> dict:
    root=root.resolve(); env=probe(root=root); src=snapshot(root); git=git_identity(root)
    tree=_git(root,'rev-parse','HEAD^{tree}')
    baseline=verify_baseline(root); catalog=validate_catalog(root)
    contracts=_contract_integrity(root)
    decision=json.loads((root/'docs/decisions/G0_CRYPTO_PROVIDER_DECISION_0066.json').read_text())
    rust_missing=[name for name in ('rustc','cargo') if not env['capabilities'].get(name,False)]
    def native_lane(goal, extra):
        if rust_missing:
            return {'status':'BLOCKED_BY_ENVIRONMENT','missing':list(rust_missing),'remediation':'Install repository-approved Rust stable/Cargo toolchain and rerun native-resume.','qualification_blockers':extra}
        return {'status':'READY','missing':[],'remediation':None,'qualification_blockers':extra}
    lanes={
        'G0-ACTOR':native_lane('G0-ACTOR',['PINNED_REAL_AUTOMERGE_IDENTITY','INDEPENDENT_COMPARISON']),
        'G0-WIRE':native_lane('G0-WIRE',['INDEPENDENT_CDDL_VALIDATOR']),
        'G0-STORE':native_lane('G0-STORE',['QUALIFIED_NATIVE_STORAGE','PHYSICAL_POWER_LOSS_EXTERNAL_LATER']),
        'G0-CRYPTO':{
            'status':'BLOCKED_BY_SECURITY_DECISION' if decision.get('status')=='DECISION_REQUIRED' else 'READY',
            'missing':['PRODUCTION_PROVIDER_DECISION'] if decision.get('selected_provider') is None else [],
            'remediation':'Complete Extra High security/provider review; do not promote legacy libsodium 1.0.18.',
            'qualification_blockers':['NATIVE_KEY_PROTECTION','INDEPENDENT_SECURITY_REVIEW','Q-SECURITY'],
        },
    }
    harness_ok=bool(baseline) and bool(catalog) and contracts['result']=='PASS'
    ready=[g for g,v in lanes.items() if v['status']=='READY']
    blocked=[g for g,v in lanes.items() if v['status']!='READY']
    return {
        'schema_version':1,'result':'PASS_PREFLIGHT_WITH_BLOCKERS' if harness_ok and blocked else ('PASS_READY' if harness_ok else 'FAIL'),
        'harness_validate':'PASS' if harness_ok else 'FAIL','contracts':contracts,
        'source':{'head':git['head'],'tree':tree,'branch':git['branch'],'dirty':git['dirty'],'source_digest':src['digest'],
                  'goal_graph_digest':_digest_file(root,'plan/tasks.json'),'requirement_authority_digest':_digest_file(root,'baseline/spec-00.02.00/MANIFEST.json')},
        'environment':{'fingerprint':env['fingerprint'],'system':env['system'],'machine':env['machine'],'rustc':env['tools']['rustc'],'cargo':env['tools']['cargo'],'cc':env['tools']['cc'],'cmake':env['tools']['cmake']},
        'lanes':lanes,'ready_lanes':ready,'blocked_lanes':blocked,
        'next_goal':'G0-ACTOR/G0-WIRE/G0-STORE isolated lanes' if not rust_missing else 'Native Readiness contracts only until Rust/Cargo are available',
        'next_command':'python3 tools/harness.py native-resume',
        'evidence_rule':'Old receipts remain historical after source/environment change; create fresh evidence only for the exact subject.',
        'durability_mode':'GIT_CHECKPOINT_PRIMARY','zip_required_per_goal':False,
        'native_qualified':False,'product_qualified':False,
    }
