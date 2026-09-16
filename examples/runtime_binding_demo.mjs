/** Synthetic live SQLite owner -> real operation inquiry -> Presenter. No production RPC. */
import {spawn} from 'node:child_process';import readline from 'node:readline';import {fileURLToPath} from 'node:url';import path from 'node:path';
import {RuntimeBinding,prepareCommand,present,formatMessage} from '../product/wp11/lib/index.js';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const child=spawn(process.env.PYTHON||'python3',['-I','-S','-B',path.join(ROOT,'tests/product/runtime-binding/owner_worker.py')],{stdio:['pipe','pipe','inherit']});
const lines=readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();
async function call(action,operationId=null){child.stdin.write(JSON.stringify({action,operationId})+'\n');const line=await lines.next();if(line.done)throw Error('worker stopped');const r=JSON.parse(line.value);if(r.error)throw Error(r.error);return r;}
try{
 const initial=await call('inspect');const pin={scope:initial.scope,deviceId:initial.deviceId,storeGeneration:initial.storeGeneration,streamId:initial.streamId};
 const b=new RuntimeBinding(pin,initial,{observe:id=>call('inspect',id),inspectOperation:id=>call('inspect',id)});
 const before=b.current;await call('commit-fixture');
 const intent=prepareCommand(before,{schemaVersion:1,kind:'inspect-operation',expectedRevision:before.revision,streamId:before.streamId,sequence:before.sequence,scope:before.scope,operationId:before.local.operationId,confirmation:null});
 const result=await b.execute(intent);if(result.outcome!=='observed')throw Error('receipt not observed');const vm=present(result.observation);
 if(vm.local.state!=='committed'||vm.document.applied||vm.sharedWriteEligible)throw Error('incorrect promotion');
 console.log(JSON.stringify({scope:'LIVE_SYNTHETIC_SQLITE_OWNER_TO_NODE_PRESENTER_ONLY',before:before.local,after:vm.local,display:formatMessage(vm.local.message,'ja'),connection:formatMessage(vm.connection.message,'ja'),metadata_only:true,shared_write_executed_by_binding:false,crdt_applied:vm.document.applied,replicated:vm.protection.observedCopies>0},null,2));
}finally{child.stdin.end();await new Promise(resolve=>{if(child.exitCode!==null)resolve();else child.once('exit',resolve);});}
