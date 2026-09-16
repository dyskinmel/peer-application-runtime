#!/usr/bin/env python3
"""Public synthetic fixture only: registered job survives retirement and executes."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_submit_retire
from submission_retire_support import RetireTest,h

def main():
    t=RetireTest('runTest');t.setUp()
    try:
        d,payload=t.ready();registered=t.st.submit(d);before=t.host.jobs.journal.path(t.jid()).read_bytes()
        request=t.retire_request(d);result=t.st.retire(request)
        assert t.host.jobs.journal.path(t.jid()).read_bytes()==before
        assert t.host.selected is None
        duplicate=t.st.retire(request);assert duplicate==result
        pin=t.st.pin();t.reopen(expected_pin=pin)
        t.host.schedule(t.jid());job=t.complete()
        try:t.st.begin(d)
        except Exception as exc:replay=exc.code
        else:raise AssertionError('retired descriptor resurrected')
        print(json.dumps({'scope':'SYNTHETIC_LOCAL_ONLY','registered':registered['state'],'retirement':result,
                          'replay':replay,'job_state_after_explicit_selection':job['state'],
                          'diagnostics':t.st.diagnostics(),'product_qualified':False},indent=2))
    finally:t.tearDown()
if __name__=='__main__':main()
