"""Declared header ancestry only. Inner Automerge hashes/operations remain opaque."""
from .errors import RecoveryError as E
from .contract import MAX_ENVELOPES

def closure(roots,headers):
    if not 1<=len(roots)<=MAX_ENVELOPES or len(set(roots))!=len(roots):raise E('ROOT_SET')
    by_change={}
    for eid,h in headers.items():by_change.setdefault(h[12],[]).append(eid)
    visiting=set();done=set();order=[]
    def visit(eid,child=None,previous=False):
        if eid not in headers:raise E('DEPENDENCY_MISSING')
        h=headers[eid]
        if child is not None:
            if (h[0],h[1],h[2],h[3])!=(child[0],child[1],child[2],child[3]):raise E('DEPENDENCY_CONTEXT')
            if previous and (h[5],h[6],h[7])!=(child[5],child[6],child[7]-1):raise E('PREVIOUS_CONTEXT')
        if eid in visiting:raise E('DEPENDENCY_CYCLE')
        if eid in done:return
        if len(visiting)+len(done)>=MAX_ENVELOPES:raise E('CLOSURE_LIMIT')
        visiting.add(eid)
        if h[8] is not None:visit(h[8],h,True)
        elif h[7]!=1:raise E('DEPENDENCY_MISSING')
        for dep in h[10]:
            options=by_change.get(dep,[])
            if not options:raise E('DEPENDENCY_MISSING')
            if len(options)!=1:raise E('DEPENDENCY_AMBIGUOUS')
            visit(options[0],h)
        visiting.remove(eid);done.add(eid);order.append(eid)
    for eid in roots:visit(eid)
    return tuple(order)
