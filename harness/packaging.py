"""Deterministic source distribution and integrity checking, not publisher authentication."""
from __future__ import annotations
import hashlib
import os
import zipfile
from pathlib import Path
from .common import HarnessError,atomic_json,read_json,file_hash,digest
from .snapshot import EXCLUDED_DIRS
SELF={'release/MANIFEST.json','release/MANIFEST.sha256'}
PRIVATE_NAMES={'.env','id_rsa','id_ed25519','credentials.json','secrets.json'}

def payload_files(root: Path) -> list[dict]:
    items=[];seen=set()
    for base,dirs,names in os.walk(root,followlinks=False):
        for name in list(dirs):
            p=Path(base)/name
            if name in EXCLUDED_DIRS:dirs.remove(name)
            elif p.is_symlink():raise HarnessError('UNSAFE_PATH',str(p))
        for name in names:
            p=Path(base)/name;rel=p.relative_to(root).as_posix()
            if rel in SELF or p.suffix=='.pyc':continue
            if p.is_symlink():raise HarnessError('UNSAFE_PATH',rel)
            if name in PRIVATE_NAMES or name.startswith('.env.') or p.suffix.lower() in ('.pem','.p12','.pfx'):
                raise HarnessError('PRIVATE_FILE',rel)
            if rel.casefold() in seen:raise HarnessError('UNSAFE_PATH','case-insensitive collision '+rel)
            seen.add(rel.casefold());items.append({'path':rel,'size':p.stat().st_size,'sha256':file_hash(p)})
    return sorted(items,key=lambda x:x['path'])

def write_manifest(root: Path) -> dict:
    entries=payload_files(root)
    m={'schema_version':1,'kind':'SOURCE_DISTRIBUTION_INTEGRITY','files':entries,'payload_digest':digest(entries),'excluded':['.git','.harness','build caches'],'not_proven':['publisher authenticity','product readiness','independent security review']}
    atomic_json(root/'release/MANIFEST.json',m)
    (root/'release/MANIFEST.sha256').write_text(file_hash(root/'release/MANIFEST.json')+'  MANIFEST.json\n',encoding='utf-8')
    return m

def verify_tree(root: Path) -> dict:
    try:
        m=read_json(root/'release/MANIFEST.json');actual=payload_files(root)
        if m.get('schema_version')!=1 or actual!=m['files'] or digest(actual)!=m['payload_digest']:
            return {'valid':False,'errors':['PAYLOAD_MISMATCH']}
        expected=(root/'release/MANIFEST.sha256').read_text().split()[0]
        if expected!=file_hash(root/'release/MANIFEST.json'):return {'valid':False,'errors':['MANIFEST_MISMATCH']}
        return {'valid':True,'files':len(actual),'payload_digest':m['payload_digest'],'errors':[]}
    except (HarnessError,OSError,ValueError,KeyError,IndexError,TypeError) as exc:
        return {'valid':False,'errors':[getattr(exc,'code',type(exc).__name__)]}

def create_archive(root: Path, output: Path) -> dict:
    root=root.resolve();output=output.resolve()
    if output.is_relative_to(root):raise HarnessError('OUTPUT_IN_SOURCE','write archive outside root')
    m=write_manifest(root)
    output.parent.mkdir(parents=True,exist_ok=True)
    names=[e['path'] for e in m['files']]+sorted(SELF)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in sorted(names):
            info=zipfile.ZipInfo(root.name+'/'+name,date_time=(2026,9,5,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3;info.external_attr=0o100644<<16
            z.writestr(info,(root/name).read_bytes())
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:raise HarnessError('ZIP_CORRUPT')
        if z.namelist()!=sorted(root.name+'/'+n for n in names):raise HarnessError('ZIP_FILE_SET')
        for name in names:
            if hashlib.sha256(z.read(root.name+'/'+name)).hexdigest()!=file_hash(root/name):raise HarnessError('ZIP_READBACK',name)
    sha=file_hash(output)
    output.with_name(output.name+'.sha256').write_text(sha+'  '+output.name+'\n',encoding='utf-8')
    return {'result':'PASS','file':output.name,'sha256':sha,'size_bytes':output.stat().st_size,'files':len(names),'manifest':verify_tree(root)}
