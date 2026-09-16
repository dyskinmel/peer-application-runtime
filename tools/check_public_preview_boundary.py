#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from harness.common import atomic_json
from harness.public_preview import scan_public_surface

CASE_IDS=(
    'public-preview.boundary',
    'public-preview.scan',
    'public-preview.unresolved-gates',
)


def _case(case_id: str, passed: bool) -> dict:
    return {'id':case_id,'status':'PASS' if passed else 'FAIL'}


def result_cases(scan: dict, policy: dict) -> list[dict]:
    findings=scan.get('findings')
    scanned=scan.get('scanned_files')
    scan_shape_ok=(
        isinstance(findings,list)
        and type(scanned) is int
        and scanned>=0
        and scan.get('publishable') is False
    )
    boundary_ok=(scan.get('pass') is True and findings==[] and scan.get('publishable') is False)
    gates_ok=(
        scan.get('unresolved_gates')==list(policy.get('unresolved_gates',[]))
        and scan.get('publishable') is False
        and policy.get('publishable') is True
        and policy.get('unresolved_gates')==[]
    )
    return [
        _case('public-preview.boundary',boundary_ok),
        _case('public-preview.scan',scan_shape_ok),
        _case('public-preview.unresolved-gates',gates_ok),
    ]


def emit_harness_result(scan: dict, policy: dict) -> bool:
    dest=os.environ.get('HARNESS_RESULT_PATH')
    if not dest:
        return True
    nonce=os.environ.get('HARNESS_NONCE')
    if not nonce:
        print('HARNESS_NONCE is required when HARNESS_RESULT_PATH is set',file=sys.stderr)
        return False
    atomic_json(Path(dest),{
        'schema_version':1,
        'nonce':nonce,
        'cases':result_cases(scan,policy),
    })
    return True


def main() -> int:
    policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
    scan=scan_public_surface(ROOT,policy)
    bound=emit_harness_result(scan,policy)
    print(json.dumps(scan,indent=2,sort_keys=True))
    if not bound:
        return 2
    return 0 if scan['pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
