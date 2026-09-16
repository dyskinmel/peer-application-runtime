#!/usr/bin/env python3
"""Measure explicit local verification reuse on public synthetic fixtures."""
import argparse,hashlib,json,sys,platform,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools.check_host_snapshot import GROUPS
from par_verified_host.benchmark import measure
from par_verified_host.host import observe_host
from snapshot_support import provider,h
from host_support import HostTest
from harness.common import atomic_json,file_hash


def run(repeats=12):
    base=provider();seed=h('benchmark');pk=base.sign_public(seed)
    tuples=[(pk,(b'public-fixture-'+str(i).encode())*16, None) for i in range(32)]
    tuples=[(k,m,base.sign(seed,m)) for k,m,_ in tuples]
    def primitive(p):
        for args in tuples:p.verify(*args)
        return len(tuples)
    primitive_report=measure(base,primitive,repeats=repeats)
    t=HostTest('runTest');t.setUp()
    try:
        t.terminal();receipt=t.finish();t.next_window(receipt);token,_=t.complete_index()
        request=t.wrap(t.cmd('progress',token));base=t.p
        def install(p):t.keeper.provider=p;t.window.provider=p;t.window._inner.provider=p
        def operation(p):return t.window.stamp(request)
        host_report=measure(base,operation,install,lambda p:observe_host(p,t.keeper,t.window),repeats=repeats)
        fixture={'request_sha256':hashlib.sha256(request).hexdigest(),'state_sha256':hashlib.sha256((t.wroot/'STATE.cbor').read_bytes()).hexdigest(),
                 'archive_sha256':[file_hash(p) for p in sorted((t.wroot/'archives').iterdir())],
                 'description':'one retained closed window plus one current committed index; identical files for both modes'}
    finally:t.tearDown()
    cpu='unknown'
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):cpu=line.split(':',1)[1].strip();break
    except OSError:pass
    source_inputs=[{'path':p.relative_to(ROOT).as_posix(),'sha256':file_hash(p)}
                   for p in sorted((ROOT/'experiments').rglob('*.py'))]
    source_inputs.append({'path':'tools/benchmark_host_snapshot.py','sha256':file_hash(ROOT/'tools/benchmark_host_snapshot.py')})
    return {'schema_version':1,'result':'PASS','environment':{'architecture':platform.machine(),'kernel':platform.release(),'cpu_model':cpu,'logical_cpus':os.cpu_count(),'network':'NONE_LOCAL_OWNER_OPERATIONS','tracemalloc_scope':'Python allocations after tracing starts; not RSS/native heap'},'source_inputs':source_inputs,'scope':'LOCAL_SYNTHETIC_MEASUREMENT_ONLY','python':platform.python_version(),
            'platform':platform.system(),'provider':base.identity,'primitive':primitive_report,'host_stamp':host_report,
            'fixture':fixture,'limits':{'default_enabled':False,'disk_reads_skipped':False,'authorization_cached':False},
            'not_established':['public-network latency','general workload speedup','native performance','whole-process RAM cap','production qualification']}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repeats',type=int,default=12);ap.add_argument('--output',type=Path);a=ap.parse_args()
    result=run(a.repeats)
    if a.output:atomic_json(a.output,result)
    print(json.dumps(result,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
