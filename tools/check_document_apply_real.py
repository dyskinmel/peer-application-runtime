#!/usr/bin/env python3
"""Optional real-Automerge3.4.1 application probe; absent core exits BLOCKED/78."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from harness.common import clean_env

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path);p.add_argument('--allow-legacy-test-libraries',action='store_true');a=p.parse_args()
 if a.manifest is None or not a.manifest.is_file():
  print(json.dumps({'result':'BLOCKED','reason':'CORE_UNAVAILABLE','real_tests_executed':0,'product_qualified':False}));return 78
 if not a.manifest.is_absolute():
  print(json.dumps({'result':'FAIL','reason':'CORE_MANIFEST_INVALID','real_tests_executed':0}));return 1
 cmd=[sys.executable,'-I','-S','-B',str(ROOT/'experiments/g0-actor/application_probe.py'),'--manifest',str(a.manifest)]
 if a.allow_legacy_test_libraries:cmd+=['--allow-legacy-test-libraries']
 try:r=subprocess.run(cmd,cwd=ROOT,env=clean_env(),capture_output=True,text=True,timeout=180)
 except subprocess.TimeoutExpired:
  print(json.dumps({'result':'BLOCKED','reason':'PROBE_TIMEOUT','real_tests_executed':'UNKNOWN','product_qualified':False}));return 78
 print(r.stdout,end='');print(r.stderr,end='',file=sys.stderr);return r.returncode
if __name__=='__main__':raise SystemExit(main())
