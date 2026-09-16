"""Test-only clock injection for a real controlled-host subprocess.

Only selector/drain module clocks are deterministic. Socket I/O, signing,
requests, activity counts and SQLite execute normally. Parent advances an atomic
file after observing DRAINING. No clock configuration is added to product CLI.
"""
import sys,types,importlib,math
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
sys.path[:0]=[str(R),str(R/'tools')]
import check_job_control
from tools.keeper_control_host import main
clock_path=Path(sys.argv.pop(1))
previous=[0.0]
def clock():
    value=float(clock_path.read_text())
    if not math.isfinite(value) or value<previous[0]:raise RuntimeError('invalid test clock')
    previous[0]=value;return value
with ExitStack() as stack:
    for name in ('par_keeper_service.server','par_window_host.server',
                 'par_job_control.server','par_job_scheduler.owner_loop'):
        stack.enter_context(patch.object(importlib.import_module(name),'time',types.SimpleNamespace(monotonic=clock)))
    raise SystemExit(main())
