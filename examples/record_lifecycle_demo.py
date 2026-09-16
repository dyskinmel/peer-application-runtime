#!/usr/bin/env python3
"""Synthetic owner-held live ledgers + separate pure model, with no deletion."""
from pathlib import Path
import argparse,hashlib,json,statistics,sys,time,tracemalloc
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_record_lifecycle
from test_lifecycle_inventory import InventoryTests,files_digest
from lifecycle_support import fixture
from par_record_lifecycle import collect_inventory,encode_inventory,plan,present,LifecycleModel

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--samples',type=int,default=5)
    ap.add_argument('--export',type=Path,help='Exclusive metadata-only inventory output; no private input payloads')
    args=ap.parse_args()
    if not 1<=args.samples<=30:ap.error('samples must be 1..30')
    test=InventoryTests('runTest');test.setUp()
    try:
        test.triple();before=files_digest(Path(test.tmp.name));timings=[];raw=None
        for _ in range(args.samples):
            start=time.perf_counter_ns();live=collect_inventory(test.st);candidate=encode_inventory(live)
            timings.append((time.perf_counter_ns()-start)/1_000_000)
            if raw is not None and candidate!=raw:raise RuntimeError('unstable live observation')
            raw=candidate
        tracemalloc.start()
        collect_inventory(test.st)
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        after=files_digest(Path(test.tmp.name))
        if before!=after:raise RuntimeError('inventory modified source ledgers')
        if args.export:
            import os
            fd=os.open(args.export,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        m=LifecycleModel(fixture());transitions=[m.view()]
        m.close(m.plan(),controller_revision=1);transitions.append(m.view())
        m.archive();transitions.append(m.view());m.compact();transitions.append(m.view())
        m.open_next(controller_revision=1);transitions.append(m.view())
        restored=LifecycleModel.restore(m.checkpoint(),expected_pin=m.pin())
        assert restored.view()==m.view()
        print(json.dumps({'scope':'LIVE_SYNTHETIC_READ_ONLY_INVENTORY_AND_SEPARATE_PURE_MODEL',
            'result':'PASS','live':present(live),'plan':plan(live),'live_files_unchanged':True,
            'inventory_bytes':len(raw),'input_digest':hashlib.sha256(raw).hexdigest(),
            'measurements':{'samples':args.samples,'milliseconds':timings,'median_ms':statistics.median(timings),
                'python_tracemalloc_peak_bytes':peak,'scope':'three records; local synthetic input; not RSS, throughput or a latency guarantee'},
            'model_transitions':transitions,'model_restore':'PASS','real_compaction_executed':False,
            'product_qualified':False},indent=2))
    finally:test.tearDown()
if __name__=='__main__':main()
