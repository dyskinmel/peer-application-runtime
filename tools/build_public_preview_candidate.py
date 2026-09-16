#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from harness.public_alpha import load_public_alpha_profile
from harness.public_preview import build_preview_archive,scan_public_surface,write_outer_sha256
p=argparse.ArgumentParser(); p.add_argument('--output',required=True); p.add_argument('--sha256-file'); p.add_argument('--release-version',default='0.1.0-alpha.1'); a=p.parse_args()
profile=load_public_alpha_profile(ROOT)
if a.release_version != profile['version']:
    print(json.dumps({'result':'FAIL','reason':'RELEASE_VERSION_MISMATCH','requested_release_version':a.release_version,'profile_release_version':profile['version']},indent=2)); raise SystemExit(1)
policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text())
scan=scan_public_surface(ROOT,policy)
if not scan['pass']:
    print(json.dumps({'result':'FAIL','reason':'PUBLIC_SURFACE_SCAN_FAILED','scan':scan},indent=2)); raise SystemExit(1)
out=build_preview_archive(ROOT,policy,Path(a.output)); out['scan']=scan
sha=write_outer_sha256(Path(a.output),Path(a.sha256_file) if a.sha256_file else None)
out['sha256_file']=str(sha)
print(json.dumps(out,indent=2,sort_keys=True)); raise SystemExit(0)
