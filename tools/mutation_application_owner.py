#!/usr/bin/env python3
"""Three targeted assertion controls on disposable copies, not independent review."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
MUTATIONS=[
 ('default-write-grant','product/wp09/par_application_owner/owner.py',
  'self._channels[channel] = OPERATIONS if allow_apply else READ_ONLY',
  'self._channels[channel] = OPERATIONS', 'owner','test_default_readonly'),
 ('omit-original-id','product/wp09/par_application_owner/owner.py',
  "intent.operation_id.hex() == args['operationId']",'True', 'owner','test_unknown_other_id_rejected'),
 ('omit-caller-persistence','product/wp11/lib/application-owner.js',
  'if (before)\n                    await before(active);',
  'if (false)\n                    await before(active);','node','application.owner.persist-before-prepare-send')]
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
 if out.is_relative_to(R):raise ValueError('output must be outside source')
 out.mkdir(parents=True,exist_ok=True);results=[]
 before_hash={p:hashlib.sha256((R/p).read_bytes()).hexdigest() for _,p,*_ in MUTATIONS}
 for label,path,before,after,group,test in MUTATIONS:
  with tempfile.TemporaryDirectory(prefix='par-owner-mutation-')as tmp:
   root=Path(tmp)/'source';shutil.copytree(R,root,ignore=shutil.ignore_patterns('.git','.harness','__pycache__','node_modules','release'))
   p=root/path;s=p.read_text()
   if s.count(before)!=1:raise RuntimeError('mutation target changed: '+label)
   p.write_text(s.replace(before,after))
   env=dict(os.environ)
   if group=='node':
    fixture=Path(tmp)/'fixture.json'
    f=subprocess.run([sys.executable,'-I','-S','-B',str(root/'tests/product/application-owner/export_fixture.py')],capture_output=True,text=True,timeout=30,check=True)
    fixture.write_text(f.stdout);env.update(PAR_ROOT=str(root),PAR_APPLICATION_FIXTURE=str(fixture))
    env.pop('HARNESS_RESULT_PATH',None);env.pop('HARNESS_NONCE',None)
    cmd=['node',str(root/'tests/product/application-owner/node_contracts.mjs')]
   else:cmd=[sys.executable,'-I','-S','-B',str(root/'tools/check_application_owner.py'),'--suite',group]
   cp=subprocess.run(cmd,capture_output=True,text=True,timeout=120,env=env);log=cp.stdout+cp.stderr;(out/(label+'.log')).write_text(log)
   marker=('FAIL: '+test+' ') if group!='node' else test+' AssertionError'
   # The JS omitted-precondition assertion can instead dereference an absent saved
   # original inside the assertion wrapper; require the precise named test FAIL.
   if group=='node':
    reports=[json.loads(l) for l in cp.stdout.splitlines() if l.startswith('{')]
    detected=cp.returncode==1 and any(any(c['id']==test and c['status']=='FAIL' for c in v.get('cases',[])) for v in reports)
   else:detected=cp.returncode==1 and marker in log
   results.append({'mutation':label,'expected_test':test,'exit_code':cp.returncode,'detected_expected_test_failure':detected,'scope':'emitted-JS runtime control' if group=='node' else 'Python source assertion control'})
 unchanged=all(hashlib.sha256((R/p).read_bytes()).hexdigest()==h for p,h in before_hash.items())
 value={'result':'PASS'if unchanged and all(v['detected_expected_test_failure']for v in results) else'FAIL','scope':'THREE_TARGETED_CONTROLS_NOT_INDEPENDENT_REVIEW','source_unchanged':unchanged,'mutations':results}
 (out/'summary.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2));return 0 if value['result']=='PASS'else 1
if __name__=='__main__':raise SystemExit(main())
