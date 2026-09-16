#!/usr/bin/env python3
"""Three bounded negative controls on disposable source copies, not an audit."""
import argparse,hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
MUTATIONS=[
 ('omit-external-fence','product/wp09/par_application_intent/journal.py',
  '        if self._anchor is not None:\n','        if False: # negative control\n',
  'application','test_dispatch_anchor_failure_never_calls_apply'),
 ('accept-regression','product/wp09/par_application_intent/anchors.py',
  "        require(value.sequence>=current.sequence,'PIN_STORE_REGRESSION')\n",'        pass # negative control\n',
  'store','test_pin_regression_rejected'),
 ('accept-unanchored','product/wp09/par_application_intent/coordinator.py',
  "        require(type(journal)is IntentJournal and journal.anchored,'PIN_STORE_REQUIRED')\n",'        pass # negative control\n',
  'application','test_unanchored_mutation_capability_refused')]
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve()
    if out.is_relative_to(R):raise ValueError('output must be outside source')
    out.mkdir(parents=True,exist_ok=True);results=[]
    hashes={p:hashlib.sha256((R/p).read_bytes()).hexdigest()for _,p,*_ in MUTATIONS}
    for label,path,before,after,group,test in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix='par-anchor-mutation-')as tmp:
            copy=Path(tmp)/'source'
            shutil.copytree(R,copy,ignore=shutil.ignore_patterns('.git','.harness','__pycache__','node_modules','release'))
            p=copy/path;raw=p.read_text()
            if raw.count(before)!=1:raise RuntimeError('mutation target changed: '+label)
            p.write_text(raw.replace(before,after))
            cp=subprocess.run([sys.executable,'-I','-S','-B',str(copy/'tools/check_intent_anchor.py'),'--suite',group],capture_output=True,text=True,timeout=120)
            log=cp.stdout+cp.stderr;(out/(label+'.log')).write_text(log)
            detected=cp.returncode==1 and ('FAIL: '+test+' ')in log
            results.append({'mutation':label,'expected_test':test,'exit_code':cp.returncode,'detected_assertion_failure':detected})
    unchanged=all(hashlib.sha256((R/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    v={'result':'PASS'if unchanged and all(r['detected_assertion_failure']for r in results)else'FAIL',
       'scope':'THREE_TARGETED_NEGATIVE_CONTROLS_NOT_INDEPENDENT_REVIEW','source_unchanged':unchanged,'mutations':results}
    (out/'summary.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v,indent=2));return 0 if v['result']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
