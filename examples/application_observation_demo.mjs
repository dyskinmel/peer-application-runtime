/** Owner-local synthetic demonstration, not production IPC or real Automerge. */
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {ApplicationReadBinding,applicationNotice} from '../product/wp11/lib/index.js';
const p=spawnSync('python3',['-I','-S','-B',fileURLToPath(new URL('./application_observation_demo.py',import.meta.url)),'--fixture'],{encoding:'utf8',timeout:15000});
if(p.status!==0)throw Error(p.stderr);
const f=JSON.parse(p.stdout);
const binding=new ApplicationReadBinding(f.pin,f.empty,{observe:async id=>{if(id!==f.recorded.operation.id)throw Error('unexpected operation');return f.recorded;}});
await binding.refresh(f.recorded.operation.id);
console.log(JSON.stringify({scope:'TYPED_CANDIDATE_OBSERVATION_NOT_CRDT',notice:applicationNotice(binding.observation),body:binding.current.document.text,localCommit:binding.current.local.state,sharedWrite:binding.current.authority.sharedWriteAllowed},null,2));
