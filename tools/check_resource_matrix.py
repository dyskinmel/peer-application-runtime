#!/usr/bin/env python3
"""Exact local matrix/pool/factory checks. No native, 7-day or P2P qualification."""
from __future__ import annotations
import argparse,json,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_application_owner
from tools.test_runner import RecordedResult
from harness.common import atomic_json
sys.path.insert(0,str(ROOT/'tests/product/resource-matrix'))
GROUPS={'pool':'test_pool.PoolTests','factory':'test_factory.FactoryTests','ledger':'test_ledger.MatrixLedgerTests','process':'test_matrix.MatrixTests'}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g])for g in(GROUPS if group=='all'else[group]))
def flatten(s):
    for t in s:
        if isinstance(t,unittest.TestSuite):yield from flatten(t)
        else:yield t
def inventory(group='all'):return sorted(t.id()for t in flatten(suite(group)))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=('all',*GROUPS),default='all');p.add_argument('--list',action='store_true');a=p.parse_args()
    if not a.list and(sys.version_info<(3,11)or not sys.platform.startswith('linux')or not Path('/proc/self/status').is_file()):
        print(json.dumps({'result':'BLOCKED','executed_cases':0,'reason':'PYTHON311_LINUX_PROC_REQUIRED'}));return 78
    expected=inventory(a.suite)
    if a.list:print(json.dumps(expected,indent=2));return 0
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite));cases=r.cases
    if r.fixture_diagnostics:print(json.dumps({'fixture_diagnostics':r.fixture_diagnostics}),file=sys.stderr)
    if os.environ.get('HARNESS_RESULT_PATH'):atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':cases})
    actual=[c['id']for c in cases];good=r.wasSuccessful()and bool(expected)and sorted(actual)==expected and len(actual)==len(set(actual))and all(c['status']=='PASS'for c in cases)
    print(json.dumps({'result':'PASS'if good else'FAIL','registered_cases':len(expected),'executed_cases':len(actual),'real_core_executed':False,'node_executed':False,'public_network_executed':False,'product_qualified':False}));return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
