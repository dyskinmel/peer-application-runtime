#!/usr/bin/env python3
"""Check syntax/types of specification-support assets, not runtime behavior."""
import argparse,hashlib,json,platform,shutil,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run():
    results=[];db=sqlite3.connect(':memory:')
    try:
        db.executescript((ROOT/'protocol/storage-v1.sql').read_text())
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        results.append({'name':'SQLite candidate DDL syntax','result':'PASS','tables':len(tables),'sqlite_version':sqlite3.sqlite_version})
        tests=[('id length',"INSERT INTO store_metadata VALUES(1,1,x'00',zeroblob(32))"),('schema version',"INSERT INTO store_metadata VALUES(1,2,zeroblob(16),zeroblob(32))"),('foreign key',"INSERT INTO actor_states VALUES(zeroblob(32),zeroblob(32),zeroblob(32),zeroblob(16),zeroblob(8),NULL)"),('non-negative resource',"INSERT INTO blocks VALUES(zeroblob(32),-1,'safe',1,'native-candidate')")]
        for name,sql in tests:
            try:db.execute(sql);rejected=False
            except sqlite3.IntegrityError:rejected=True
            finally:db.rollback()
            results.append({'name':'DDL rejects '+name,'result':'PASS' if rejected else 'FAIL'})
    except Exception as exc:results.append({'name':'SQLite candidate DDL syntax','result':'FAIL','error':str(exc)})
    finally:db.close()
    tsc=shutil.which('tsc')
    if tsc:
        cmd=[tsc,'--noEmit','--strict','--target','ES2020','--lib','ES2020,DOM','api/par-contracts.d.ts','api/example-contract.ts']
        try:
            v=subprocess.run([tsc,'--version'],capture_output=True,text=True,timeout=20)
            p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=45)
            results.append({'name':'TypeScript declarations/example','result':'PASS' if p.returncode==0 else 'FAIL','command':cmd,'version':v.stdout.strip(),'executable':str(Path(tsc).resolve()),'executable_sha256':hashlib.sha256(Path(tsc).resolve().read_bytes()).hexdigest(),'stdout':p.stdout,'stderr':p.stderr,'exit_code':p.returncode})
        except Exception as exc:results.append({'name':'TypeScript declarations/example','result':'BLOCKED','error':str(exc)})
    else:results.append({'name':'TypeScript declarations/example','result':'BLOCKED','reason':'tsc is not installed; no network install attempted'})
    cases=json.loads((ROOT/'fixtures/wire-samples.json').read_text())['cases']
    try:
        for case in cases:bytes.fromhex(case['hex'])
        sample=bytes.fromhex(cases[0]['hex']);assert int.from_bytes(sample[:4],'big')==len(sample)-4
        results.append({'name':'Wire fixture byte formatting only','result':'PASS','cases':len(cases),'not_executed':'CBOR/CDDL parsing or expected semantic rejection'})
    except Exception as exc:results.append({'name':'Wire fixture byte formatting only','result':'FAIL','error':str(exc)})
    return {'scope':'SPEC_SUPPORT_ASSETS_ONLY','python':sys.version,'platform':platform.platform(),'results':results,'result':'FAIL' if any(x['result']=='FAIL' for x in results) else 'BLOCKED' if any(x['result']=='BLOCKED' for x in results) else 'PASS','not_established':['SQLite crash durability','product API behavior','wire conformance','production readiness']}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path);a=p.parse_args();r=run();s=json.dumps(r,ensure_ascii=False,indent=2);print(s)
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(s+'\n')
    return 0 if r['result']=='PASS' else 2 if r['result']=='BLOCKED' else 1
if __name__=='__main__':sys.exit(main())
