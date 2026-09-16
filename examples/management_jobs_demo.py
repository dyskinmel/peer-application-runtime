#!/usr/bin/env python3
"""Public synthetic fixture, actual SQLite/crypto, no user files or sockets."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_management_jobs import GROUPS
from jobs_support import JobTest
from par_management_jobs.presenter import present

def main():
    t=JobTest();t.setUp()
    try:
        rows=[]
        j=t.jid('cancel');cmd=t.retired_command()
        t.jobs.submit(j,action='retire',command=cmd);rows.append(t.jobs.cancel(j))
        # Cancelling this job does not revoke the separately authorized request.
        t.window.execute(cmd)
        archive,close=t.proposed();args=dict(action='close',command=close,archive=archive);j=t.jid('close')
        rows.append(t.jobs.submit(j,**args));t.prepare(j)
        fired=[False]
        def lose_ack(stage):
            if stage=='job.effect.after_dispatch' and not fired[0]:
                fired[0]=True;raise OSError('synthetic response loss AFTER backend effect')
        t.jobs.journal.observer=lose_ack
        rows.append(t.jobs.step(j));pin=t.jobs.pin()
        t.reopen_jobs(expected_pin=pin);rows.append(t.jobs.reconcile(j))
        compact=t.jid('compact');t.jobs.submit(compact,action='compact');t.complete(compact);receipt=t.jobs.result(compact)
        op=t.jid('open');grant=t.grant_for(2,t.w.digest(receipt));t.jobs.submit(op,action='open',command=grant);rows.append(t.complete(op))
        print(json.dumps({'scope':'SYNTHETIC_LOCAL_DEMO','rows':rows,'presentation':[present(r) for r in rows],'window_sequence':t.window.pin()[1],'live_host_integrated':False,'product_qualified':False},ensure_ascii=False,indent=2))
    finally:t.tearDown()
if __name__=='__main__':main()
