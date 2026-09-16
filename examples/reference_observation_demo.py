#!/usr/bin/env python3
"""Run the existing REAL LOCAL synthetic recovery, then adapt its report for display.
No real user data or secrets. Its booleans are an observation, not cryptographic proof.
"""
import json,subprocess,sys,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.check_reference_presenter import build
from harness.common import clean_env
with tempfile.TemporaryDirectory(prefix='par-presentation-observation-') as tmp:
    dest=Path(tmp);compiler=build(dest);env=clean_env()
    result=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'examples/recovery_demo.py')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
    if result.returncode:print(result.stderr,file=sys.stderr);raise SystemExit(result.returncode)
    report=json.loads(result.stdout);(dest/'report.json').write_text(json.dumps(report))
    script="""
import fs from 'node:fs';import {pathToFileURL} from 'node:url';
const api=await import(pathToFileURL(process.env.BUILD+'/index.js').href);
const report=JSON.parse(fs.readFileSync(process.env.BUILD+'/report.json'));
const source=JSON.parse(fs.readFileSync(process.env.ROOT+'/product/wp11/fixtures/states.json'))[1].state;
source.protection.root=report.after_validation.roots[0];source.evidence={kind:'runtime-observation',references:['existing local recovery demo; synthetic keys and plaintext']};
source.supportedCommands=['open-details'];source.sequence='2';source.revision='recovery-observed';
const vm=api.present(api.adaptRecoveryStatus(source,report.after_validation));
if(vm.document.applied||vm.document.innerValidated||vm.recovery.writable||vm.sharedWriteEligible)throw Error('unsupported promotion');
console.log(JSON.stringify({scope:'LOCAL_RECOVERY_REPORT_TO_PRESENTER_ONLY',donor_db_removed:report.donor_db_removed,after_validation:report.after_validation,display:api.formatMessage(vm.primary,'ja'),actions:vm.actions,document_applied:vm.document.applied,shared_write:vm.sharedWriteEligible,no_rendered_ui:true},null,2));
"""
    env.update(BUILD=tmp,ROOT=str(ROOT))
    raise SystemExit(subprocess.run([compiler['node'],'--input-type=module','-e',script],cwd=ROOT,env=env).returncode)
