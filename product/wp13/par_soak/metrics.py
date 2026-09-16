"""Linux quiescent observations; RSS is approximate process memory, not a proof.

Preconnected descriptors reserved for future rounds are measured separately.
A missing reservation is an error, never a subtraction that conceals a leak.
Node active resource TYPES are not an inventory of every JS promise/object.
"""
from __future__ import annotations
import asyncio,os
from collections import Counter
from pathlib import Path
from .campaign import need

RSS_GROWTH_BUDGET=64*1024**2  # diagnostic local campaign budget, not PAR product SLO

def sample_python(reserved):
    need(type(reserved)is list and len(reserved)==len(set(reserved))and all(type(i)is int and i>=0 for i in reserved),'RESERVED_FD')
    # Ignore the readdir FD, which is already closed before readlink.
    opened={}
    for p in Path('/proc/self/fd').iterdir():
        try:opened[int(p.name)]=os.readlink(p)
        except FileNotFoundError:continue
    need(set(reserved)<=opened.keys(),'RESERVED_FD_MISSING')
    fields={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:','VmHWM:')):
            k,value,unit=line.split();need(unit=='kB','METRIC_RSS_UNIT');fields[k[:-1]]=int(value)*1024
    need('VmRSS'in fields and 'VmHWM'in fields,'METRIC_UNAVAILABLE')
    return {'pid':os.getpid(),'raw_fd':len(opened),'reserved_fd':len(reserved),
            'fd':len(opened)-len(reserved),'tasks':sum(not t.done()for t in asyncio.all_tasks()),
            'rss_bytes':fields['VmRSS'],'rss_high_water_bytes':fields['VmHWM']}

def _metrics(row,keys):
    need(type(row)is dict,'METRIC_SCHEMA')
    for k in ('pid','fd','rss_bytes',*keys):need(type(row.get(k))is int and row[k]>=0,'METRIC_'+k.upper())
    need(type(row.get('segment'))is str and 0<len(row['segment'])<=100,'METRIC_SEGMENT')

def compare_resources(base_py,base_node,current_py,current_node):
    """Return violations; missing/ill-typed evidence raises, never defaults to 0."""
    for r in (base_py,current_py):_metrics(r,('tasks','channels','inflight'))
    for r in (base_node,current_node):
        _metrics(r,('pendingStore','pendingRequests','inflight'))
        need(type(r.get('active'))is dict and all(type(k)is str and type(v)is int and v>=0 for k,v in r['active'].items()),'METRIC_ACTIVE')
    need((base_py['pid'],base_py['segment'])==(current_py['pid'],current_py['segment'])and
         (base_node['pid'],base_node['segment'])==(current_node['pid'],current_node['segment']),'METRIC_SEGMENT_CHANGED')
    bad=[]
    for name,b,c in (('PYTHON',base_py,current_py),('NODE',base_node,current_node)):
        if c['fd']>b['fd']:bad.append(name+'_FD_GROWTH')
        if c['rss_bytes']-b['rss_bytes']>RSS_GROWTH_BUDGET:bad.append(name+'_RSS_BUDGET')
    if current_py['tasks']>base_py['tasks']:bad.append('PYTHON_TASK_GROWTH')
    if current_py['channels']or current_py['inflight']:bad.append('PYTHON_PENDING')
    if current_node['pendingStore']or current_node['pendingRequests']or current_node['inflight']:bad.append('NODE_PENDING')
    if any(v>base_node['active'].get(k,0)for k,v in current_node['active'].items()):bad.append('NODE_ACTIVE_GROWTH')
    return bad
