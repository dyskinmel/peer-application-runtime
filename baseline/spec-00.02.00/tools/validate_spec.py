#!/usr/bin/env python3
"""Offline structural checks for this SPECIFICATION, not a product conformance suite."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
from typing import Any

def strict_pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out: raise ValueError(f'duplicate JSON key: {key}')
        out[key]=value
    return out

def read_json(path:Path)->Any:
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=strict_pairs)

def validate(root:Path, check_manifest:bool=False)->dict:
    root=root.resolve(); errors=[]; checks=0
    def check(condition:bool,message:str):
        nonlocal checks
        checks+=1
        if not condition: errors.append(message)
    try:
        for p in root.rglob('*.json'):
            read_json(p)
        req=read_json(root/'catalog/requirements.json')
        tests=read_json(root/'catalog/acceptance-tests.json')
        docs=read_json(root/'catalog/documents.json')
        gates=read_json(root/'catalog/gates.json')
        status=read_json(root/'STATUS.json')
        rmap={r['id']:r for r in req}; tmap={t['id']:t for t in tests}; gmap={g['id']:g for g in gates}
        check(len(rmap)==len(req),'duplicate requirement ID')
        check(len(tmap)==len(tests),'duplicate test ID')
        check(len(gmap)==len(gates)==12,'gate IDs must be 12 unique entries')
        check(set(gmap)=={f'G{i}' for i in range(12)},'unexpected gate set')
        check(len({d['domain'] for d in docs})==len(docs),'duplicate spec domain')
        check(status['artifact_kind']=='SPECIFICATION_ONLY','incorrect artifact kind')
        check(status['product_implementation']=='NOT_STARTED','product implementation falsely advanced')
        check(status['product_runtime_tests_executed']==0,'product test claim without implementation')
        check(status['independent_security_reviews_completed']==0,'independent review claim in unreviewed bundle')
        check(status['qualified_profiles']==[],'unverified production-qualified profile')
        check(all(v=='NOT_RUN' for v in status['gates'].values()),'unexecuted product gate promoted')
        for r in req:
            path=root/r['spec']
            check(path.is_file(),f'missing spec {r["spec"]}')
            if path.is_file():
                txt=path.read_text()
                check(f'id="{r["anchor"]}"' in txt,f'missing anchor {r["id"]}')
                check(r['statement'] in txt,f'catalog/body mismatch {r["id"]}')
            check(r['gate'] in gmap,f'invalid gate {r["id"]}')
            check(r['implementation_status']=='NOT_STARTED',f'false implementation claim {r["id"]}')
            check(r['evidence_status']=='NOT_RUN',f'false evidence claim {r["id"]}')
            check(bool(r['test_ids']),f'missing acceptance reference {r["id"]}')
            for tid in r['test_ids']:
                check(tid in tmap,f'unknown test {tid}')
                if tid in tmap: check(r['id'] in tmap[tid]['requirements'],f'broken reverse link {tid}')
        for t in tests:
            check(t['execution_status']=='NOT_RUN',f'unexecuted acceptance marked complete {t["id"]}')
            check(t['implementation_path'] is None,f'phantom implementation path {t["id"]}')
            check(len(t.get('positive',''))>8 and len(t.get('negative',''))>8,f'empty acceptance cases {t["id"]}')
            for rid in t['requirements']:
                check(rid in rmap,f'unknown requirement {rid}')
                if rid in rmap: check(t['id'] in rmap[rid]['test_ids'],f'broken test mapping {t["id"]}')
        for d in docs:
            check(sum(r['domain']==d['domain'] for r in req)==d['requirements'],f'doc requirement count mismatch {d["path"]}')
        visiting=set(); visited=set()
        def visit(gid):
            if gid in visiting: raise ValueError('cyclic gate dependency')
            if gid in visited:return
            if gid not in gmap:raise ValueError(f'missing dependency {gid}')
            visiting.add(gid)
            for other in gmap[gid]['depends_on']:visit(other)
            visiting.remove(gid);visited.add(gid)
        for g in gates:
            visit(g['id'])
            check(g['state']=='NOT_RUN',f'false gate completion {g["id"]}')
            check(set(g['first_required_requirement_ids'])=={r['id'] for r in req if r['gate']==g['id']},f'gate requirement mismatch {g["id"]}')
        for w in read_json(root/'catalog/work-packages.json'):
            check(w['gate'] in gmap,f'unknown WP gate {w["id"]}')
            check(w['state']=='NOT_STARTED',f'false WP claim {w["id"]}')
        known_sources={s['id'] for s in read_json(root/'catalog/sources.json')}
        for p in root.rglob('*.md'):
            txt=p.read_text()
            for sid in re.findall(r'\[(S\d{2})\]',txt):check(sid in known_sources,f'unknown source {sid} in {p.name}')
            for link in re.findall(r'\[[^\]]*\]\(([^\s\)]+)\)',txt):
                if re.match(r'^[a-zA-Z]+:',link) or link.startswith('#'):continue
                target=link.split('#',1)[0]
                if target:check((p.parent/target).resolve().exists(),f'broken local link {p.relative_to(root)} -> {link}')
        registry=read_json(root/'protocol/registry.json')
        cddl=(root/'protocol/par-v1.cddl').read_text()
        definitions=re.findall(r'^([a-zA-Z][a-zA-Z0-9-]*)\s*=',cddl,re.M)
        check(len(definitions)==len(set(definitions)),'duplicate CDDL named rule')
        messages=registry['messages'];check(len({x['code'] for x in messages})==len(messages),'duplicate message code')
        for m in messages:
            check(m['body_type'] in definitions,f'missing CDDL body {m["name"]}')
            check(f'1: {m["code"]},' in cddl,f'missing frame discriminant {m["name"]}')
        check(len(set(registry['domain_labels']))==len(registry['domain_labels']),'duplicate crypto label')
        check(len({e['code'] for e in registry['errors']})==len(registry['errors']),'duplicate error code')
        lim=read_json(root/'protocol/limits.json')['hard']
        check(lim['frame_body_bytes']==1048576,'frame limit inconsistent with draft')
        check(lim['block_plain_bytes']<lim['change_plain_bytes']<lim['envelope_bytes']<lim['frame_body_bytes'],'inconsistent nested byte limits')
        # Basic token graph, not full DTCG conformance or rendered contrast checks.
        tokens={}
        def collect(obj,prefix=''):
            if isinstance(obj,dict) and '$value' in obj:
                check(prefix not in tokens,f'duplicate token {prefix}');tokens[prefix]=obj
            elif isinstance(obj,dict):
                for k,v in obj.items():
                    if not k.startswith('$'):collect(v,prefix+'.'+k if prefix else k)
        for p in (root/'tokens').glob('*.tokens.json'):collect(read_json(p))
        def resolve(name,stack):
            if name in stack:raise ValueError(f'token alias cycle {name}')
            if name not in tokens:raise ValueError(f'unknown token {name}')
            val=tokens[name]['$value']
            if isinstance(val,str) and val.startswith('{') and val.endswith('}'):
                return resolve(val[1:-1],stack+[name])
            return val
        for name,t in tokens.items():
            check('$type' in t,f'missing token type {name}')
            val=resolve(name,[])
            if t['$type']=='color':check(isinstance(val,dict) and len(val.get('components',[]))==3 and all(0<=v<=1 for v in val['components']),f'invalid seed color {name}')
        themes=read_json(root/'tokens/themes.json')
        for group in ['modes','density','motion']:
            for name,overrides in themes[group].items():
                for key,val in overrides.items():
                    check(key in tokens,f'unknown theme target {key}')
                    if isinstance(val,str) and val.startswith('{'):check(val[1:-1] in tokens,f'unknown theme alias {val}')
        stories=read_json(root/'ui/stories.json');commands=read_json(root/'api/ui-command-registry.json')['commands']
        check(len({s['id'] for s in stories})==len(stories),'duplicate UI story ID')
        ts=(root/'api/par-contracts.d.ts').read_text()
        for cmd in commands:check(repr(cmd) in ts,f'UI action absent in TS declaration {cmd}')
        for story in stories:
            check(story['execution_status']=='NOT_RUN',f'false UI execution {story["id"]}')
            for a in story['allowed_actions']:check(a in commands,f'unknown UI action {a}')
            for f in story['forbidden_claims']:check(f not in story['required_text'],f'UI required text contradicts forbidden claim {story["id"]}')
        primitive=read_json(root/'fixtures/primitive-kats.json')['ed25519']
        for field,length in [('secret_seed_hex',64),('public_key_hex',64),('signature_hex',128)]:
            check(bool(re.fullmatch('[0-9a-f]{'+str(length)+'}',primitive[field])),f'invalid primitive vector length {field}')
        origin=read_json(root/'history/ORIGIN.json')
        check(hashlib.sha256((root/'history'/origin['file']).read_bytes()).hexdigest()==origin['sha256'],'historical baseline changed')
        if check_manifest:
            manifest=read_json(root/'MANIFEST.json');listed=set()
            for item in manifest['files']:
                rel=item['path'];p=root/rel;listed.add(rel)
                check(p.is_file(),f'missing manifest file {rel}')
                if p.is_file():
                    check(p.stat().st_size==item['size_bytes'],f'manifest size mismatch {rel}')
                    check(hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],f'manifest digest mismatch {rel}')
            actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','MANIFEST.sha256'] and '__pycache__' not in p.parts}
            check(listed==actual,'manifest file set mismatch')
        counts={'spec_documents':len(docs),'requirements':len(req),'acceptance_contracts':len(tests),'positive_scenarios':len(tests),'negative_scenarios':len(tests),'gates':len(gates),'wire_messages':len(messages),'ui_stories':len(stories),'tokens':len(tokens)}
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}');counts={}
    return {'schema_version':1,'scope':'SPECIFICATION_STRUCTURE_ONLY','result':'FAIL' if errors else 'PASS','checks_evaluated':checks,'counts':counts,'errors':errors,'not_established':['runtime behavior','CDDL parser conformance','composed protocol cryptography','real device UI','production readiness']}

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument('--check-manifest',action='store_true');ap.add_argument('--report',type=Path);args=ap.parse_args()
    report=validate(args.root,args.check_manifest);txt=json.dumps(report,ensure_ascii=False,indent=2)
    print(txt)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(txt+'\n')
    return 0 if report['result']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
