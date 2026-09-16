#!/usr/bin/env python3
"""Disposable synthetic demo: register over IPC, then select separately."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_job_submit
from test_submit_restart import SubmitHostProcess
x=SubmitHostProcess('test_separate_process_registration_then_selection')
try:
    x.setUp();r=x.prep();x.start_host();client,d=x.transfer(r)
    ready=client.call('progress',d);registered=client.call('submit',d);control=x.control_client()
    before=control.call('status',x.jid);assert before['job']['state']=='QUEUED' and before['host']['selected_job'] is None
    from submit_support import h
    control.call('select',x.jid,h('demo-select'))
    for _ in range(50):
        after=control.call('status',x.jid)
        if after['job']['state']=='SUCCEEDED':break
    assert after['job']['state']=='SUCCEEDED'
    print(json.dumps({'scope':'SYNTHETIC_PRIVATE_LOCAL_PROCESSES','staged':ready['state'],'registered':registered['state'],'before_explicit_selection':before['job']['state'],'after_explicit_selection':after['job']['state'],'product_qualified':False},indent=2))
finally:x.tearDown()
