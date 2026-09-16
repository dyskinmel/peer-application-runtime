#!/usr/bin/env python3
"""One-shot local migration child used only by the SIGKILL recovery tests."""
from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from product.wp14.par_migration import plan_migration, run_migration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--kill-stage", required=True)
    parser.add_argument("--available-bytes", required=True, type=int)
    args = parser.parse_args()

    plan = plan_migration(
        Path(args.store_root),
        Path(args.work_root),
        observed_at=args.observed_at,
        capacity_reader=lambda _: args.available_bytes,
    )
    seen = False

    def observer(stage: str) -> None:
        nonlocal seen
        if stage == args.kill_stage:
            seen = True
            os.kill(os.getpid(), signal.SIGKILL)

    run_migration(plan, observer=observer)
    if not seen:
        print(f"kill stage was not observed: {args.kill_stage}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
