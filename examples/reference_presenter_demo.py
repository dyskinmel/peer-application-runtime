#!/usr/bin/env python3
"""Compile to a temporary directory and run a display/IME contract demonstration."""
import os,subprocess,sys,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.check_reference_presenter import build
from harness.common import clean_env
with tempfile.TemporaryDirectory(prefix='par-presenter-demo-') as tmp:
    compiler=build(Path(tmp));env=clean_env();env.update(PAR_ROOT=str(ROOT),PAR_PRESENTER_BUILD=tmp)
    raise SystemExit(subprocess.run([compiler['node'],str(ROOT/'examples/reference_presenter_demo.mjs')],cwd=ROOT,env=env).returncode)
