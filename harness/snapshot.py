"""Relocatable content snapshots. State/output exclusions are fixed, not per task."""
from __future__ import annotations
import os
from pathlib import Path
from .common import HarnessError, digest, file_hash, read_json, safe_path

EXCLUDED_DIRS = {'.git','.harness','__pycache__','.venv','node_modules','target','dist'}
EXCLUDED_PATHS = {'release/evidence','release/archives','release/MANIFEST.json','release/MANIFEST.sha256','release/STATUS.json'}

def excluded(rel: str) -> bool:
    p = Path(rel)
    return any(x in EXCLUDED_DIRS for x in p.parts) or any(rel==x or rel.startswith(x+'/') for x in EXCLUDED_PATHS) or p.suffix=='.pyc'

def snapshot(root: Path) -> dict:
    root = root.resolve(); files = []
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            p=Path(base)/name; rel=p.relative_to(root).as_posix()
            if excluded(rel): dirs.remove(name)
            elif p.is_symlink(): raise HarnessError('UNSAFE_PATH', 'source directory symlink '+rel)
        for name in names:
            p=Path(base)/name; rel=p.relative_to(root).as_posix()
            if excluded(rel): continue
            if p.is_symlink() or not p.is_file(): raise HarnessError('UNSAFE_PATH', rel)
            files.append({'path':rel,'size':p.stat().st_size,'sha256':file_hash(p)})
    files.sort(key=lambda x:x['path'])
    return {'algorithm':'sha256-canonical-file-set-v1','files':files,'digest':digest(files)}

def diff(a: dict, b: dict) -> list[str]:
    aa={x['path']:(x['sha256'],x['size']) for x in a['files']}; bb={x['path']:(x['sha256'],x['size']) for x in b['files']}
    return sorted(k for k in aa.keys()|bb.keys() if aa.get(k)!=bb.get(k))

def allowed(path: str, prefixes: list[str]) -> bool:
    return any(path==p or (p.endswith('/') and path.startswith(p)) for p in prefixes)

def guard_digest(root: Path) -> str:
    snap=snapshot(root)
    guarded=[x for x in snap['files'] if x['path'].startswith(('policy/','plan/','harness/','baseline/','tools/','tests/')) or x['path'] in ('AGENTS.md','SPEC.md','PLANS.md')]
    return digest(guarded)

def verify_baseline(root: Path) -> dict:
    pin=read_json(safe_path(root,'policy/baseline.json')); b=safe_path(root,pin['root'])
    found=[]
    for p in sorted(b.rglob('*')):
        rel=p.relative_to(b).as_posix()
        if '__pycache__' in p.parts or p.suffix=='.pyc': continue
        if p.is_symlink(): raise HarnessError('BASELINE_CHANGED',rel)
        if p.is_file(): found.append({'path':rel,'size':p.stat().st_size,'sha256':file_hash(p)})
    if found!=pin['files']: raise HarnessError('BASELINE_CHANGED','file set or content differs')
    return {'result':'PASS','files':len(found),'archive_sha256':pin['archive_sha256']}
