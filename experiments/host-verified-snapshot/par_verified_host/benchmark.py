"""Bounded synthetic full/cached comparison. Timings are observations, not gates."""
import hashlib,json,statistics,time,tracemalloc
from .provider import VerificationProvider


def _distribution(samples):
    a=sorted(samples)
    return {'count':len(a),'median_ns':int(statistics.median(a)),
            'p95_ns':a[min(len(a)-1,(95*len(a)+99)//100-1)],'min_ns':a[0],'max_ns':a[-1]}


def measure(base, operation, install=lambda p:None, observe=lambda p:None, *, repeats=12):
    """Use the same fixture for both modes; measure latency and memory separately.

    Operations MUST be read-only/diagnostic. Returns no input/key bytes. Full/cached
    ordering alternates in two rounds; results must agree in all observations.
    """
    if type(repeats) is not int or not 1<=repeats<=32:raise ValueError('repeats must be 1..32')
    rounds=[];all_results=[]
    for order in (('full','signatures'),('signatures','full')):
        for mode in order:
            p=VerificationProvider(base,mode=mode);samples=[]
            try:
                install(p);observe(p)
                for _ in range(repeats):
                    t=time.perf_counter_ns();value=operation(p);samples.append(time.perf_counter_ns()-t)
                    all_results.append(hashlib.sha256(repr(value).encode()).hexdigest())
                counts=p.statistics()
            finally:install(base);p.close()
            # Fresh instance for bounded heap observation; do not pollute timings.
            p=VerificationProvider(base,mode=mode)
            try:
                install(p);tracemalloc.start();observe(p)
                for _ in range(3):operation(p)
                retained,peak=tracemalloc.get_traced_memory()
            finally:tracemalloc.stop();install(base);p.close()
            rounds.append({'order':list(order),'mode':mode,'latency':_distribution(samples),
                           'verification':counts,'tracemalloc_bytes':{'current':retained,'peak':peak}})
    if len(set(all_results))!=1:raise AssertionError('full and cached observable results differ')
    return {'scope':'SYNTHETIC_LOCAL_OBSERVATION_NOT_PERFORMANCE_SLA','result_digest':all_results[0],
            'same_results':True,'repeats_per_round':repeats,'rounds':rounds}
