#!/usr/bin/env python3
"""Bounded successful signature reuse; no product/readiness claim."""
import argparse, os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_window_host import GROUPS as HOST_GROUPS
for p in ('experiments/host-verified-snapshot','tests/product/host-verified-snapshot'):sys.path.insert(0,str(ROOT/p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={'contract':'test_snapshot_contract','limits':'test_snapshot_limits','service':'test_snapshot_host.CachedWindowService','live':'test_snapshot_host.SnapshotLiveState','process':'test_snapshot_process','faults':'test_snapshot_faults','io':'test_snapshot_io'}
def suite(group='all'):
    out=unittest.TestSuite()
    for g in (GROUPS if group=='all' else [group]):
        if g=='live':
            from test_snapshot_host import SnapshotLiveState
            out.addTests(SnapshotLiveState(n) for n in sorted(SnapshotLiveState.__dict__) if n.startswith('test_'))
        else:out.addTest(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]))
    return out
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--suite',choices=['all']+list(GROUPS),default='all');a=ap.parse_args()
    r=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':r.cases})
    return 0 if r.wasSuccessful() and r.cases and all(c['status']=='PASS' for c in r.cases) else 1
if __name__=='__main__':raise SystemExit(main())
