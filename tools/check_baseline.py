#!/usr/bin/env python3
import importlib.util
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from harness.common import atomic_json
from harness.snapshot import verify_baseline

def main():
    cases=[]
    try:verify_baseline(ROOT);cases.append({'id':'baseline.bytes','status':'PASS'})
    except Exception as e:print(type(e).__name__,str(e));cases.append({'id':'baseline.bytes','status':'FAIL'})
    base=ROOT/'baseline/spec-00.02.00'
    spec=importlib.util.spec_from_file_location('frozen_baseline_validator',base/'tools/validate_spec.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=module.validate(base,True)
    print('Original baseline:',report)
    cases.append({'id':'baseline.structure','status':report['result']})
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ['HARNESS_NONCE'],'cases':cases})
    return 0 if all(c['status']=='PASS' for c in cases) else 1
if __name__=='__main__':raise SystemExit(main())
