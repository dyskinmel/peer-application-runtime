#!/usr/bin/env python3
"""Three targeted mutation probes in disposable copies; not an independent review."""
import argparse,hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROBES=[
 ('dispatch-before-apply','product/wp09/par_application_intent/coordinator.py',
  'self.journal.dispatch(digest);dispatched=True','dispatched=True',
  'test_intent_coordinator.IntentCoordinatorTests.test_synthetic_transaction_after_dispatch_only'),
 ('original-operation-id','product/wp09/par_application_intent/model.py',
  "row['operationId']==intent.operation_id.hex()",'True',
  'test_intent_journal.IntentJournalTests.test_receipt_wrong_operation_revision_targets_rejected'),
 ('known-tail-pin','product/wp09/par_application_intent/journal.py',
  "require(len(names)>=expected.sequence,'JOURNAL_PIN')","require(True,'JOURNAL_PIN')",
  'test_intent_journal.IntentJournalTests.test_pin_prevents_known_tail_deletion')]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);records=[]
    before={name:sha(ROOT/name) for _,name,*_ in PROBES}
    for label,name,old,new,case in PROBES:
        with tempfile.TemporaryDirectory(prefix='par-intent-mutation-')as tmp:
            dest=Path(tmp)/'source'
            shutil.copytree(ROOT,dest,ignore=shutil.ignore_patterns('.git','.harness','release','__pycache__','node_modules','.pytest_cache'))
            p=dest/name;text=p.read_text();assert text.count(old)==1,(label,text.count(old));p.write_text(text.replace(old,new))
            code="import sys,unittest;sys.path[:0]="+repr([str(dest),str(dest/'tools')])+";import check_application_intent;unittest.main(module=None,argv=['test',"+repr(case)+"])"
            cp=subprocess.run([sys.executable,'-I','-S','-B','-c',code],capture_output=True,text=True,timeout=60)
            log=cp.stdout+cp.stderr;(args.output/(label+'.log')).write_text(log)
            caught=cp.returncode==1 and 'AssertionError' in log and 'FAILED (failures=' in log
            records.append({'probe':label,'case':case,'exit_code':cp.returncode,'detected':caught})
    unchanged=before=={name:sha(ROOT/name) for name in before}
    value={'result':'PASS' if unchanged and all(r['detected']for r in records)else'FAIL','scope':'THREE_TARGETED_MUTANTS_NOT_COVERAGE_OR_INDEPENDENT_REVIEW','original_source_unchanged':unchanged,'probes':records}
    (args.output/'result.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))
    return 0 if value['result']=='PASS'else 1
if __name__=='__main__':raise SystemExit(main())
