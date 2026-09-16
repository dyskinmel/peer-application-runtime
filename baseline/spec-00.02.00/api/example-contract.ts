/** Compile-only illustrative contract; the runtime has NOT been implemented. */
import {PeerRuntime, type Result, type Runtime} from './par-contracts';
function unwrap<T>(r:Result<T>):T { if (!r.ok) throw new Error(r.error.code); return r.value; }
export async function sharedNotesContract():Promise<Runtime> {
  const runtime=unwrap(await PeerRuntime.open({
    appId:'org.example.shared-notes',identity:{mode:'platform-keystore'},
    storage:{mode:'platform-default',encryption:'required'},
    connectivity:{profile:'participants-only',discovery:['invitation','known-peers'],bootstrapPeers:[],relayPeers:[]},
    contribution:{storeForOthers:false,relayForOthers:false},
  }));
  const space=unwrap(await runtime.spaces.create({
    operationId:runtime.newOperationId(),label:'Family Notes',
    schemas:[{id:'note.v1',fields:{title:{type:'register<string>',maxUtf8Bytes:1024},body:{type:'text',maxUtf8Bytes:1048576}}}],
    replication:{remoteRetainedCopies:2},
  }));
  const created=unwrap(await space.docs.create({operationId:runtime.newOperationId(),schemaId:'note.v1',initial:{title:'旅行の予定',body:''}}));
  const reading=unwrap(await created.document.read());
  if(reading.state!=='found') return runtime;
  const snapshot=reading.snapshot;
  const operationId=runtime.newOperationId();
  const changed=await created.document.change(operationId,tx=>{
    tx.textSplice(['body'],{scalarOffset:0,frontier:snapshot.frontier},0,'集合場所を決める');
  });
  if (!changed.ok) {
    if(changed.error.code==='LOCAL_OUTCOME_UNKNOWN') await runtime.lookupOperation(operationId);
    return runtime;
  }
  // Replication timeout does not undo local commit. The UI displays the actual status.
  const remote=await space.replication.wait(changed.value.commitId,{remoteRetainedCopies:2,timeoutMs:5000});
  if(remote.ok && !remote.value.satisfied) console.info('この端末に保存済み。ほかの端末への複製を待っています。');
  return runtime;
}
