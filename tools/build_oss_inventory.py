#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.public_alpha import load_public_alpha_profile, validate_public_alpha_profile

BASELINE_HEAD='2452b0ebb5bbc0e4b0322ea67f1c4ff80406100e'
BASELINE_TREE='fa8c93f46a8e7b79ead9f8b11450b49b8c66bf26'
BASELINE_SOURCE_DIGEST='8959dcac8450766248d3f846743781d6ef123a67468dfdca6285b709becb7b59'
INVENTORY_GENERATION_METADATA=ROOT/'oss/INVENTORY_GENERATION_METADATA.json'


def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_manifest_binds_inventory_metadata()->bool:
    manifest_path=ROOT/'PUBLIC_SOURCE_MANIFEST.json'
    try:
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    files=manifest.get('files') if isinstance(manifest,dict) else None
    if not isinstance(files,list):
        return False
    rows=[row for row in files if isinstance(row,dict) and row.get('path')=='oss/INVENTORY_GENERATION_METADATA.json']
    return len(rows)==1 and rows[0].get('sha256')==sha(INVENTORY_GENERATION_METADATA)

def git_tracked(pattern:str)->list[str]:
    try:
        cp=subprocess.run(['git','-C',str(ROOT),'ls-files',pattern],check=True,text=True,capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            p.relative_to(ROOT).as_posix()
            for p in ROOT.rglob(pattern)
            if p.is_file()
        )
    return sorted(x for x in cp.stdout.splitlines() if x)

def load_inventory_generation_metadata()->dict:
    metadata=json.loads(INVENTORY_GENERATION_METADATA.read_text(encoding='utf-8'))
    if not isinstance(metadata,dict):
        raise ValueError('INVENTORY_GENERATION_METADATA_INVALID:NOT_OBJECT')
    profile_sha=sha(ROOT/'oss/PUBLIC_ALPHA_RELEASE.json')
    profile_source=metadata.get('profile_source')
    errors=[]
    if metadata.get('schema_version') != 1: errors.append('schema_version')
    if metadata.get('profile_sha256') != profile_sha: errors.append('profile_sha256')
    if not isinstance(profile_source,dict) or profile_source.get('path') != 'oss/PUBLIC_ALPHA_RELEASE.json' or not profile_source.get('commit') or not profile_source.get('commit_timestamp'):
        errors.append('profile_source')
    if metadata.get('inventory_snapshot_created') != (profile_source.get('commit_timestamp') if isinstance(profile_source,dict) else None):
        errors.append('inventory_snapshot_created')
    if metadata.get('creation_info_semantics') != 'DETERMINISTIC_INVENTORY_SNAPSHOT_NOT_DEVELOPMENT_BASELINE_TIME': errors.append('creation_info_semantics')
    if errors:
        raise ValueError('INVENTORY_GENERATION_METADATA_INVALID:'+json.dumps(errors,sort_keys=True))
    commit=profile_source['commit']
    if not isinstance(commit,str) or not re.fullmatch(r'[0-9a-f]{40}',commit):
        raise ValueError('INVENTORY_GENERATION_METADATA_INVALID:profile_source.commit')
    try:
        source=subprocess.run(['git','-C',str(ROOT),'cat-file','blob',f"{commit}:{profile_source['path']}"],capture_output=True)
    except OSError:
        source=None
    if source is None or source.returncode:
        # A distributed source archive has no Git database. In that case the
        # checked profile digest still binds the deterministic inventory
        # snapshot, but historical provenance is deliberately not claimed.
        try:
            repository=subprocess.run(
                ['git','-C',str(ROOT),'rev-parse','--is-inside-work-tree'],
                capture_output=True,
                text=True,
            )
        except OSError:
            repository=None
        if repository is not None and repository.returncode == 0 and repository.stdout.strip() == 'true':
            if not source_manifest_binds_inventory_metadata():
                errors.append('profile_source.commit_unavailable')
    else:
        if hashlib.sha256(source.stdout).hexdigest() != metadata['profile_sha256']:
            errors.append('profile_source.profile_sha256')
        timestamp=subprocess.run(['git','-C',str(ROOT),'show','-s','--format=%ct',commit],check=True,capture_output=True,text=True)
        created=datetime.fromtimestamp(int(timestamp.stdout.strip()),timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        if profile_source['commit_timestamp'] != created:
            errors.append('profile_source.commit_timestamp')
    if errors:
        raise ValueError('INVENTORY_GENERATION_METADATA_INVALID:'+json.dumps(errors,sort_keys=True))
    return metadata

def package_manifests()->list[dict]:
    rows=[]
    for rel in git_tracked('*package.json'):
        p=ROOT/rel; d=json.loads(p.read_text(encoding='utf-8'))
        rows.append({
            'path':rel,
            'name':d.get('name','UNKNOWN'),
            'version':d.get('version','UNKNOWN'),
            'private':d.get('private','UNKNOWN'),
            'license_declared':d.get('license','UNKNOWN'),
            'dependencies':d.get('dependencies',{}),
            'devDependencies':d.get('devDependencies',{}),
            'optionalDependencies':d.get('optionalDependencies',{}),
            'peerDependencies':d.get('peerDependencies',{}),
            'scripts':d.get('scripts',{}),
            'sha256':sha(p),
        })
    return rows

def dependency_rows()->list[dict]:
    crypto=json.loads((ROOT/'policy/crypto-provider.json').read_text(encoding='utf-8'))
    reviewed_on='2026-09-16'
    return [
        {
            'name':'libsodium-ctypes-local-candidate','version':crypto.get('version','UNKNOWN'),
            'source':'policy/crypto-provider.json','relationship':'DIRECT','scope':'reference_runtime_crypto',
            'detected_license':'ISC','license_status':'REVIEWED_OFFICIAL_SOURCE',
            'license_evidence':{'source_kind':'OFFICIAL_UPSTREAM','url':'https://github.com/jedisct1/libsodium/blob/1.0.18/LICENSE','reviewed_on':reviewed_on},
            'pin_status':'PINNED_BINARY_SHA256',
            'maintenance_status':'UNKNOWN','native_or_future':'CURRENT_REFERENCE_EXPERIMENT_AND_NATIVE_DECISION_INPUT',
            'inclusion_status':'SOURCE_REFERENCE_ONLY_BINARY_NOT_BUNDLED','transitive_dependencies':'UNKNOWN',
            'security_qualified':bool(crypto.get('security_qualified',False)),
            'sha256':crypto.get('sha256','UNKNOWN')
        },
        {
            'name':'sqlite','version':'>=3.37 reference requirement; exact runtime varies',
            'source':'experiments/g0-store/README.ja.md','relationship':'DIRECT','scope':'reference_runtime_store',
            'detected_license':'LicenseRef-SQLite-Public-Domain','license_status':'REVIEWED_OFFICIAL_SOURCE',
            'license_evidence':{'source_kind':'OFFICIAL_UPSTREAM','url':'https://www.sqlite.org/copyright.html','reviewed_on':reviewed_on},
            'pin_status':'FLOATING_SYSTEM_RUNTIME',
            'maintenance_status':'UNKNOWN','native_or_future':'CURRENT_REFERENCE_AND_FUTURE_NATIVE_STORAGE_DECISION',
            'inclusion_status':'SYSTEM_RUNTIME_NOT_BUNDLED','transitive_dependencies':'NOT_APPLICABLE_LOCAL_METADATA',
            'security_qualified':False
        },
        {
            'name':'typescript-compiler','version':'UNKNOWN',
            'source':'product/wp10/package.json#scripts.build','relationship':'DIRECT_TOOL_UNDECLARED','scope':'development_build_tool',
            'detected_license':'Apache-2.0','license_status':'REVIEWED_OFFICIAL_SOURCE',
            'license_evidence':{'source_kind':'OFFICIAL_UPSTREAM','url':'https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt','reviewed_on':reviewed_on},
            'pin_status':'FLOATING_UNDECLARED',
            'maintenance_status':'UNKNOWN','native_or_future':'DEVELOPMENT_TOOL',
            'inclusion_status':'NOT_BUNDLED','transitive_dependencies':'UNKNOWN','security_qualified':'NOT_APPLICABLE'
        },
        {
            'name':'automerge-native-dependency','version':'UNKNOWN',
            'source':'handoff/native_readiness/contracts/g0-actor.json','relationship':'FUTURE_DIRECT','scope':'future_native_actor',
            'detected_license':'MIT','license_status':'REVIEWED_OFFICIAL_SOURCE',
            'license_evidence':{'source_kind':'OFFICIAL_UPSTREAM','url':'https://github.com/automerge/automerge/blob/main/LICENSE','reviewed_on':reviewed_on},
            'pin_status':'NOT_SELECTED',
            'maintenance_status':'RESEARCH_REQUIRED','native_or_future':'FUTURE_NATIVE_DEPENDENCY',
            'inclusion_status':'NOT_SELECTED_NOT_BUNDLED','transitive_dependencies':'UNKNOWN','security_qualified':False
        },
        {
            'name':'production-crypto-provider','version':'UNKNOWN',
            'source':'docs/decisions/G0_CRYPTO_PROVIDER_DECISION_0066.json','relationship':'FUTURE_DIRECT','scope':'future_native_crypto',
            'detected_license':'UNKNOWN','license_status':'FUTURE_SELECTION_REQUIRED',
            'license_evidence':{'source_kind':'NOT_APPLICABLE_UNSELECTED','url':None,'reviewed_on':reviewed_on},
            'pin_status':'NOT_SELECTED',
            'maintenance_status':'RESEARCH_REQUIRED','native_or_future':'FUTURE_NATIVE_DEPENDENCY',
            'inclusion_status':'DECISION_REQUIRED_NOT_BUNDLED','transitive_dependencies':'UNKNOWN','security_qualified':False
        }
    ]

def build_dependency_inventory()->dict:
    return {
        'schema_version':1,
        'classification':'PRE_RELEASE_SOURCE_DEPENDENCY_INVENTORY_NOT_FINAL_RESOLUTION',
        'development_baseline':{'head':BASELINE_HEAD,'tree':BASELINE_TREE,'source_digest':BASELINE_SOURCE_DIGEST},
        'network_resolution_performed':False,
        'package_manifests':package_manifests(),
        'dependencies':dependency_rows(),
        'limitations':[
            'no registry/network resolution was performed',
            'transitive dependency closure is UNKNOWN where no lockfile or resolved native graph exists',
            'native production and platform dependencies remain unresolved',
            'license and maintenance status are not inferred from package names'
        ]
    }

def build_third_party(dep:dict, profile:dict)->dict:
    material=[]
    for rel in ('LICENSE','NOTICE'):
        p=ROOT/rel
        material.append({
            'path':rel,
            'sha256':sha(p),
            'status':'FINAL_REPOSITORY_LICENSE_MATERIAL',
            'included_in_public_candidate':True,
        })
    declarations=[]
    for m in dep['package_manifests']:
        declarations.append({'path':m['path'],'package':m['name'],'declared_license':m['license_declared'],'status':'COMPONENT_METADATA_ONLY_NOT_REPOSITORY_LICENSE_DECISION'})
    return {
        'schema_version':2,
        'release_license_decision':profile['license']['spdx'],
        'license_authorized_for_publication':False,
        'repository_license_material_complete':True,
        'repository_license_material':material,
        'manifest_license_declarations':declarations,
        'dependency_license_status':[{'name':d['name'],'detected_license':d['detected_license'],'status':d['license_status'],'license_evidence':d['license_evidence'],'inclusion_status':d['inclusion_status']} for d in dep['dependencies']],
        'files_requiring_notice_review':[],
        'third_party_compatibility':'REVIEWED_NO_BUNDLED_THIRD_PARTY_ARTIFACTS',
        'source_only_alpha_dependency_review':{
            'status':'COMPLETED',
            'reviewed_on':'2026-09-16',
            'scope':'DECLARED_AND_REFERENCED_UNBUNDLED_DEPENDENCIES',
            'conclusion':'NO_KNOWN_LICENSE_CONFLICT_FOR_SOURCE_ONLY_ALPHA_SCOPE',
            'limitations':[
                'factual upstream license review only; not legal advice',
                'no third-party binary or native dependency bundle is distributed',
                'the production crypto provider remains unselected and requires a new review before distribution',
                'transitive and native dependency closure remains required before binary or native-artifact distribution'
            ]
        },
        'potential_license_conflicts':[],
        'legal_conclusion':'FACTUAL_LICENSE_REVIEW_COMPLETED_NOT_LEGAL_ADVICE'
    }

def build_license_gate(profile:dict)->dict:
    return {
        'schema_version':2,
        'status':'RESOLVED_SOURCE_ONLY_ALPHA',
        'publishable':False,
        'selected_spdx_license':profile['license']['spdx'],
        'final_license_text':profile['license']['license_file'],
        'copyright_holder':profile['copyright']['public_holder'],
        'notice_finalized':True,
        'external_publish_prerequisites':profile['external_publish_prerequisites'],
        'baseline_license_is_release_authorization':False
    }

def spdx_id(name:str)->str:
    safe=''.join(c if c.isalnum() else '-' for c in name).strip('-') or 'unknown'
    return 'SPDXRef-'+safe[:80]

def build_sbom(dep:dict, profile:dict, metadata:dict)->dict:
    canonical=json.dumps(dep,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    inv_digest=hashlib.sha256(canonical).hexdigest()
    project_id='SPDXRef-PAR-Source-Candidate'
    packages=[{
        'SPDXID':project_id,'name':profile['project']['name'],'versionInfo':profile['version'],
        'downloadLocation':'NOASSERTION','filesAnalyzed':False,'licenseConcluded':'NOASSERTION','licenseDeclared':profile['license']['spdx'],
        'copyrightText':'NOASSERTION'
    }]
    relationships=[{'spdxElementId':'SPDXRef-DOCUMENT','relationshipType':'DESCRIBES','relatedSpdxElement':project_id}]
    seen={project_id}
    for row in dep['dependencies']:
        sid=spdx_id(row['name'])
        n=1; base=sid
        while sid in seen:
            n+=1; sid=f'{base}-{n}'
        seen.add(sid)
        lic=row['detected_license'] if row['detected_license'] not in ('UNKNOWN',None) else 'NOASSERTION'
        packages.append({
            'SPDXID':sid,'name':row['name'],'versionInfo':row['version'],'downloadLocation':'NOASSERTION',
            'filesAnalyzed':False,'licenseConcluded':'NOASSERTION','licenseDeclared':lic,'copyrightText':'NOASSERTION',
            'comment':f"scope={row['scope']}; inclusion={row['inclusion_status']}; maintenance={row['maintenance_status']}"
        })
        relationships.append({'spdxElementId':project_id,'relationshipType':'DEPENDS_ON','relatedSpdxElement':sid})
    return {
        'spdxVersion':'SPDX-2.3','dataLicense':'CC0-1.0','SPDXID':'SPDXRef-DOCUMENT',
        'name':'PAR-SOURCE-SBOM-CANDIDATE','documentNamespace':f'urn:par:source-sbom-candidate:{inv_digest}',
        'creationInfo':{'created':metadata['inventory_snapshot_created'],'creators':['Tool: PAR tools/build_oss_inventory.py']},
        'packages':packages,'relationships':relationships,
        'parMetadata':{
            'final':False,'classification':'SOURCE_ONLY_ALPHA_DEPENDENCY_INVENTORY',
            'developmentBaselineHead':BASELINE_HEAD,'dependencyInventorySha256':inv_digest,
            'sourceOnlyRelease':True,
            'nativeArtifactBundled':False,
            'nativeDependencySbomStatus':profile['source_only']['native_dependency_sbom']['status'],
            'nativeDependencySbomRequiredBefore':profile['source_only']['native_dependency_sbom']['required_before'],
            'networkResolutionPerformed':False,
            'creationInfoSemantics':metadata['creation_info_semantics']
        }
    }

def write_json(path:Path,data:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')

def render(out:Path)->dict[str,dict]:
    profile=load_public_alpha_profile(ROOT)
    errors=validate_public_alpha_profile(ROOT, profile)
    if errors:
        raise ValueError('PUBLIC_ALPHA_PROFILE_INVALID:'+json.dumps(errors,sort_keys=True))
    metadata=load_inventory_generation_metadata()
    dep=build_dependency_inventory(); third=build_third_party(dep, profile); gate=build_license_gate(profile); sbom=build_sbom(dep, profile, metadata)
    outputs={
        'DEPENDENCY_INVENTORY.json':dep,'THIRD_PARTY_INVENTORY.json':third,
        'LICENSE_DECISION_REQUIRED.json':gate,'SBOM.spdx.json':sbom,
    }
    for name,data in outputs.items(): write_json(out/name,data)
    return outputs

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',default=str(ROOT/'oss')); ap.add_argument('--check',action='store_true'); a=ap.parse_args()
    out=Path(a.output_dir)
    if a.check:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            expected=render(Path(td)); failures=[]
            for name in expected:
                target=out/name; candidate=Path(td)/name
                if not target.exists() or target.read_bytes()!=candidate.read_bytes(): failures.append(name)
            print(json.dumps({'result':'PASS' if not failures else 'FAIL','mismatches':failures},indent=2))
            return 0 if not failures else 1
    render(out)
    print(json.dumps({'result':'PASS','output_dir':str(out),'files':['DEPENDENCY_INVENTORY.json','THIRD_PARTY_INVENTORY.json','LICENSE_DECISION_REQUIRED.json','SBOM.spdx.json']},indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
