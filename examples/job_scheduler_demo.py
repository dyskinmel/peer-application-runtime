#!/usr/bin/env python3
"""Synthetic fixtures and real private sockets; no user data or public network."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_job_scheduler import GROUPS
from scheduler_support import SchedulerTest
from par_job_scheduler.presenter import present

def main():
    t=SchedulerTest();t.setUp()
    try:
        t.start_host();t.submit_close();client,hello=t.connect(True)
        rows=[t.host.diagnostics()];t.host.schedule(t.jid());t.tick(3)
        rows.append(t.host.diagnostics());assert t.window.phase=='OPEN'
        assert t.host.jobs.poll(t.jid())['state']=='PREPARED'
        client.close();t.complete();rows.append(t.host.diagnostics())
        assert t.window.phase=='CLOSED'
        print(json.dumps({'scope':'SYNTHETIC_LOCAL_REAL_SOCKET_DEMO','scheduler':rows,
             'presentation':[present(r) for r in rows], 'result':t.host.jobs.poll(t.jid()),
             'management_socket':False,'preemptive_cancellation':False,'product_qualified':False},ensure_ascii=False,indent=2))
    finally:t.tearDown()
if __name__=='__main__':main()
