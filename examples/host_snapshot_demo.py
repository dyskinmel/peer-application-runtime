#!/usr/bin/env python3
"""Public synthetic fixture comparison; temporary data only, no public listeners."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools.benchmark_host_snapshot import run
if __name__=='__main__':
    data=run(4)
    print(json.dumps({'scope':data['scope'],'same_results':data['host_stamp']['same_results'],'rounds':[{'mode':r['mode'],'median_ns':r['latency']['median_ns'],'backend_calls':r['verification']['backend_calls'],'hits':r['verification']['hits'],'tracemalloc_peak_bytes':r['tracemalloc_bytes']['peak']} for r in data['host_stamp']['rounds']],'production_qualified':False},indent=2))
