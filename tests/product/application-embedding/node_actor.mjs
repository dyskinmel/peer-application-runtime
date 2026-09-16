import net from 'node:net';import assert from 'node:assert/strict';
import {ConnectedApplicationChannel} from '../../../product/wp11/node/application-channel.mjs';
import {LocalCallerIntent} from '../../../product/wp11/node/caller-intent.mjs';
import {ApplicationEmbedding} from '../../../product/wp11/lib/application-embedding.js';
import {mountReference} from '../../../product/wp11/lib/renderer.js';
import {state} from '../wp11/support.mjs';import {Document,find} from './dom-support.mjs';
const [fd,text,ids,directory,mode]=process.argv.slice(2),context=JSON.parse(text),targets=JSON.parse(ids);
const channel=new ConnectedApplicationChannel(new net.Socket({fd:Number(fd),readable:true,writable:true}),{expectedContext:context,requestTimeoutMs:10000,helloTimeoutMs:10000});
let embedding,view;const calls=[];const store=new LocalCallerIntent(directory);const port={request(...a){calls.push(a[0]);return channel.request(...a);},close(){return channel.close();}};
try{
 await channel.ready;embedding=new ApplicationEmbedding(context,store,targets,{localExperiment:true});embedding.attach(context,port);
 const doc=new Document(),root=doc.createElement('div'),note=state();note.scope={appId:context.document.scope.appId,spaceId:context.document.scope.spaceId,documentId:context.document.scope.documentId};note.authority.controlHead=context.document.scope.controlHead;note.authority.epoch=context.document.scope.epoch;
 view=mountReference(root,note,{applicationEmbedding:embedding});assert.equal(calls.length,0);assert.equal(await store.load()===null,mode!=='recover');
 const action=op=>find(root,e=>e.dataset.applicationAction===op);
 const click=async op=>{const b=action(op);assert.ok(b);assert.equal(b.disabled,false,op+' disabled');await b.onclick();};
 const review=()=>{const b=find(root,e=>e.dataset.applicationField==='review');assert.equal(b.disabled,false);b.checked=true;b.onchange();};
 if(mode==='recover'){
  await click('restore');assert.equal(calls.length,0);await click('observe');await click('inquire');assert.equal(embedding.current.original.operationId,'6f'.repeat(16));assert.deepEqual(calls,['observe','inquire']);
 }else if(mode==='readonly'){
  await click('observe');assert.equal(action('prepare').disabled,true);assert.equal(action('dispatch').disabled,true);
 }else{
  find(root,e=>e.dataset.applicationField==='operationId').value='6f'.repeat(16);
  await click('stage');assert.equal(calls.length,0);assert.equal((await store.load()).dispatchAttempted,false);
  if(mode!=='stage-only'){
   await click('observe');await click('prepare');
   if(mode!=='kill-prepare'){
    assert.equal(embedding.current.snapshot.journal.state,'PREPARED');
    if(mode==='marker-only'){
     const mark=store.markDispatch.bind(store);store.markDispatch=async id=>{await mark(id);view.destroy();};
    }
    review();await click('dispatch');
    if(['complete','kill-retire'].includes(mode)){await click('inquire');review();await click('retire');}
    if(mode==='blocked'){assert.equal(embedding.current.snapshot.journal.operationState,'CORE_BLOCKED');assert.equal(action('dispatch').disabled,true);}
   }
  }
 }
 const before=embedding.current,stored=await store.load();view.destroy();let cleanupRejected=false;
 try{await view.applicationCleanup();}catch{cleanupRejected=true;}
 // A detach made inside a persistence callback first reports pending cleanup.
 await new Promise(r=>setImmediate(r));assert.equal(embedding.checkCleanup(),true);
 assert.deepEqual(await store.load(),stored);assert.equal(channel.stats().inflight,0);
 console.log(JSON.stringify({state:before,stored,calls,cleanupRejected,cleanup:embedding.current.lifecycle,channel:channel.stats()}));
}catch(e){console.error(e.stack);process.exitCode=1;}finally{view?.destroy();await embedding?.detach().catch(()=>{});await channel.close();}
