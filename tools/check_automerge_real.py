#!/usr/bin/env python3
"""Explicit real-core gate. Missing manifest is BLOCKED (78), never a green skip."""
import argparse,json,os,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from harness.common import clean_env

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--manifest',type=Path);a.add_argument('--allow-legacy-test-libraries',action='store_true');ns=a.parse_args()
 if ns.manifest is None or not ns.manifest.is_file():
  print(json.dumps({'result':'BLOCKED','reason':'CORE_UNAVAILABLE','real_tests_executed':0,'core_qualified':False,'next':'Read product/wp04/README.ja.md; obtain and review the real artifact outside this tool.'}));return 78
 if not ns.manifest.is_absolute():print(json.dumps({'result':'FAIL','reason':'CORE_MANIFEST_INVALID'}));return 1
 cmds=[['node',str(R/'experiments/g0-actor/real_cases.mjs'),str(ns.manifest)],
       [sys.executable,'-I','-S','-B',str(R/'experiments/g0-actor/store_probe.py'),'--manifest',str(ns.manifest)]+(['--allow-legacy-test-libraries'] if ns.allow_legacy_test_libraries else [])]
 for cmd in cmds:
  try:r=subprocess.run(cmd,cwd=R,env=clean_env(),capture_output=True,text=True,timeout=150)
  except (OSError,subprocess.TimeoutExpired):print(json.dumps({'result':'BLOCKED','reason':'CORE_UNAVAILABLE_OR_TIMEOUT'}));return 78
  print(r.stdout,end='');print(r.stderr,end='',file=sys.stderr)
  if r.returncode:return r.returncode
 return 0
if __name__=='__main__':sys.exit(main())
