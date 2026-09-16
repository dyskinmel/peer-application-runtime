#!/usr/bin/env python3
"""Run with Python 3.10+; no pip installation required."""
import sys
from pathlib import Path
if sys.version_info<(3,10):raise SystemExit('Python 3.10 or newer is required.')
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.cli import main
if __name__=='__main__':raise SystemExit(main())
