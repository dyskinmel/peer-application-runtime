"""Synthetic-only host death at an exact persistence boundary; no detached child."""
import os,signal,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools import keeper_retire_control_host as cli
from par_submit_retire_control import host
point=sys.argv.pop(1)
Original=host.RetirementControlHost
class FaultHost(Original):
    def __init__(self,*a,**kw):
        def stop(event):
            if event==point:
                print(json.dumps({'hit':event,'pgid':os.getpgrp()}),flush=True)
                os.kill(os.getpid(),signal.SIGKILL)
        kw['submission_observer']=stop
        super().__init__(*a,**kw)
host.RetirementControlHost=FaultHost
if __name__=='__main__':raise SystemExit(cli.main())
