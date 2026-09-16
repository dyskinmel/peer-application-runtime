#!/usr/bin/env python3
"""Disposable public-key fixtures: real owner client and host; no user data."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import check_job_control
from test_control_restart import ControlHostProcess

def main():
    fixture=ControlHostProcess();fixture.setUp()
    try:
        fixture.start_host();queued=fixture.control();selected=fixture.control('select')
        for _ in range(40):
            done=fixture.control()
            if done['job']['state']=='SUCCEEDED':break
        assert done['job']['state']=='SUCCEEDED'
        duplicate=fixture.control('select');assert duplicate['duplicate']
        print(json.dumps({'scope':'PRIVATE_SYNTHETIC_DEMO','before':queued['job']['state'],'selection_ack':selected['outcome'],
              'after':done['job']['state'],'duplicate_ack':duplicate['duplicate'],'automatic_replay':False,'product_qualified':False},indent=2))
    finally:fixture.tearDown()
if __name__=='__main__':main()
