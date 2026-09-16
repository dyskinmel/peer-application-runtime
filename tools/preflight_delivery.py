#!/usr/bin/env python3
"""Cheap release-entry consistency only; NEVER substitutes test execution."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

def check(root:Path)->dict:
    errors=[]
    try:
        version=json.loads((root/'policy/branding.json').read_text())['artifact_version']
        source=json.loads((root/'plan/experiment-state.json').read_text())['source']
        if type(version) is not str or re.fullmatch(r'\d{2}\.\d{2}\.\d{2}',version) is None:
            errors.append('VERSION_FORMAT')
        else:
            if source!=version:errors.append('VERSION_MISMATCH:experiment-state')
            if (root/'README.md').read_text().splitlines()[0]!='# Peer Application Runtime — development kit '+version:
                errors.append('VERSION_MISMATCH:README')
            if version not in (root/'START_HERE.ja.md').read_text().splitlines()[0]:
                errors.append('VERSION_MISMATCH:START_HERE')
            if version not in (root/'AGENTS.md').read_text():errors.append('VERSION_MISMATCH:AGENTS')
        if (root/'AGENTS.md').stat().st_size>4000:errors.append('AGENTS_OVER_BUDGET')
    except (OSError,ValueError,KeyError,IndexError,TypeError):errors.append('METADATA_UNREADABLE')
    return {'result':'PASS' if not errors else 'FAIL','scope':'METADATA_PREFLIGHT_NOT_TEST_OR_QUALIFICATION','errors':errors,'product_qualified':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=p.parse_args()
    result=check(args.root);print(json.dumps(result,indent=2));return 0 if result['result']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
