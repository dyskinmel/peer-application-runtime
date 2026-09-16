#!/usr/bin/env python3
"""Recipient-bound closure experiment, not production qualification."""
from __future__ import annotations
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from tools.check_file import GROUPS as FILE_GROUPS
sys.path.insert(0,str(ROOT/'experiments/recovery-closure'))
sys.path.insert(0,str(ROOT/'tests/product/recovery-closure'))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_recovery_contract','pipeline':'test_recovery_pipeline','transfer':'test_recovery_transfer','faults':'test_recovery_faults'}
def suite(group='all'):
    names=list(GROUPS.values()) if group=='all' else [GROUPS[group]]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=ap.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
