#!/usr/bin/env python3
"""Targeted destructive controls in disposable source copies; not an audit."""
import argparse,hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from harness.snapshot import snapshot
CONTROLS=[
 ('fairness','product/wp13/par_matrix/pool.py',"self._cursor=(i+1)%len(self._peers)","self._cursor=0",'test_pool.py','round_robin_not_global_fifo'),
 ('connection_close','product/wp13/par_matrix/pool.py',"try:await j.connection.close()","try:pass",'test_pool.py','normal_closes_before_success'),
 ('child_exit_cardinality','product/wp13/par_matrix/campaign.py',"payload['child_exit_codes']==expected","True",'test_ledger.py','wrong_exit_count_refused'),
]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.resolve().is_relative_to(ROOT):raise ValueError('OUTPUT_OUTSIDE_SOURCE_REQUIRED')
 a.output.mkdir(parents=True,exist_ok=False);before=snapshot(ROOT);results=[]
 for name,path,old,new,file,case in CONTROLS:
  with tempfile.TemporaryDirectory(prefix='par0055-control-')as td:
   dest=Path(td)/'source';shutil.copytree(ROOT,dest,ignore=shutil.ignore_patterns('.git','.harness','release','__pycache__','node_modules'))
   f=dest/path;s=f.read_text()
   if s.count(old)!=1:raise ValueError('CONTROL_SITE_NOT_UNIQUE:'+name)
   f.write_text(s.replace(old,new))
   command=[sys.executable,'-B','-m','unittest','discover','-s','tests/product/resource-matrix','-p',file,'-k',case,'-v']
   r=subprocess.run(command,cwd=dest,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
   (a.output/(name+'.log')).write_text(r.stdout)
   detected=r.returncode!=0 and 'AssertionError' in r.stdout and 'FAILED (failures=1)'in r.stdout and 'Ran 1 test'in r.stdout
   results.append({'name':name,'argv':command,'changed_path':path,'replacement':[old,new],'exit_code':r.returncode,'detected_by_assertion':detected})
 result={'result':'PASS'if all(x['detected_by_assertion']for x in results)and snapshot(ROOT)==before else'FAIL','controls':results,'source_unchanged':snapshot(ROOT)==before,'scope':'THREE_TARGETED_CONTROLS_ONLY','independent_review':'NOT_RUN'}
 (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['result']=='PASS'else 1
if __name__=='__main__':raise SystemExit(main())
