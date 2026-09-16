/** Persistent real Node/owner-wire actor; timeout callback and close failure are
 * deliberate provider fixtures. No DOM, TLS, public listener or CRDT claim. */
import net from 'node:net';import fs from 'node:fs';import readline from 'node:readline';
import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
import {setImmediate as tick} from 'node:timers/promises';
import {ConnectedApplicationChannel} from '../../../product/wp11/node/application-channel.mjs';
import {LocalCallerIntent} from '../../../product/wp11/node/caller-intent.mjs';
import {ApplicationEmbedding} from '../../../product/wp11/lib/application-embedding.js';
import {applicationOwnerKey} from '../../../product/wp11/lib/application-owner.js';
const [text,ids,directory,fdsText]=process.argv.slice(2),ctx=JSON.parse(text),targets=JSON.parse(ids),fds=JSON.parse(fdsText);
const send=v=>process.stdout.write(JSON.stringify(v)+'\n');
const stream=readline.createInterface({input:process.stdin});const iterator=stream[Symbol.asyncIterator]();
const receive=async()=>{const r=await iterator.next();if(r.done)throw new Error('CONTROL_EOF');return JSON.parse(r.value);};
const store=new LocalCallerIntent(directory);const original={profile:'par-caller-application-0052',ownerKey:applicationOwnerKey(ctx),operationId:'6f'.repeat(16),expectedRevision:0,targets};
await store.save(original);await store.markDispatch(original.operationId);
const fingerprint=()=>fs.readdirSync(directory).sort().map(n=>[n,createHash('sha256').update(fs.readFileSync(directory+'/'+n)).digest('hex')]);
const before=fingerprint();let embedding=new ApplicationEmbedding(ctx,store,targets),used=0;
function measure(reserved){
 const opened=new Set();for(const n of fs.readdirSync('/proc/self/fd')){try{fs.readlinkSync('/proc/self/fd/'+n);opened.add(Number(n));}catch(e){if(e.code!=='ENOENT')throw e;}}
 for(const n of reserved)assert.ok(opened.has(n),'RESERVED_FD_MISSING');
 const active={};for(const k of process.getActiveResourcesInfo())active[k]=(active[k]??0)+1;
 const memory=process.memoryUsage();return{pid:process.pid,raw_fd:opened.size,reserved_fd:reserved.length,fd:opened.size-reserved.length,active,rss_bytes:memory.rss,heap_used_bytes:memory.heapUsed,external_bytes:memory.external,array_buffers_bytes:memory.arrayBuffers};
}
send({kind:'ready',pid:process.pid});
try{
 while(true){
  const command=await receive();if(command.cmd==='exit')break;
  assert.equal(command.cmd,'round');const {round,scenario}=command;
  if(embedding.current.lifecycle==='CLEANUP_UNCONFIRMED')embedding=new ApplicationEmbedding(ctx,store,targets);
  const socket=new net.Socket({fd:fds[used++],readable:true,writable:true});const closed=new Promise(r=>socket.once('close',r));
  const channel=new ConnectedApplicationChannel(socket,{expectedContext:ctx,requestTimeoutMs:30000,helloTimeoutMs:30000});
  let closeCalls=0;const port={request:(...args)=>channel.request(...args),async close(){closeCalls++;await channel.close();if(scenario==='close-failure')throw new Error('INJECTED_CLOSE_FAILURE');}};
  let code=null,deadlineCallback=null;const started=process.hrtime.bigint();let shutdown=started;
  try{
   await channel.ready;embedding.attach(ctx,port);await embedding.restore();assert.equal(embedding.current.dispatchAttempted,true);
   if(['cancel','timeout','disconnect'].includes(scenario)){
    // Capture only the client deadline timer; the timeout path is triggered AFTER
    // the owner has acknowledged entering its waiting operation. Not an elapsed-
    // wall-time performance assertion and not a changed production timeout limit.
    const realSetTimeout=globalThis.setTimeout;let deadlineHandle;
    if(scenario==='timeout')globalThis.setTimeout=(fn,ms,...a)=>{if(ms===54321){deadlineCallback=()=>fn(...a);deadlineHandle=realSetTimeout(()=>{},60000);return deadlineHandle;}return realSetTimeout(fn,ms,...a);};
    let pending;try{pending=embedding.observe({timeoutMs:scenario==='timeout'?54321:30000}).then(()=>({ok:true}),e=>({ok:false,code:e.code}));}finally{globalThis.setTimeout=realSetTimeout;}
    send({kind:'started',round});const trigger=await receive();assert.equal(trigger.cmd,'trigger');assert.equal(trigger.round,round);
    if(scenario==='cancel')embedding.cancel();
    else if(scenario==='disconnect')socket.destroy();
    else{assert.equal(typeof deadlineCallback,'function');deadlineCallback();}
    const result=await pending;assert.equal(result.ok,false);code=result.code;
    assert.equal(code,scenario==='timeout'?'APPLICATION_TIMEOUT':scenario==='cancel'?'CANCELLED':'HOST_DISCONNECTED');
   }else{
    await embedding.observe({timeoutMs:30000});
    if(scenario==='inquire'){await embedding.inquire({timeoutMs:30000});assert.equal(embedding.current.snapshot.journal.operationState,'NOT_OBSERVED');}
    if(scenario==='reject'){
     try{await channel.request('prepare',{context:ctx},new AbortController().signal);throw new Error('GRANT_BYPASSED');}catch(e){assert.equal(e.code,'OWNER_OPERATION_DENIED');code=e.code;}
    }
   }
   shutdown=process.hrtime.bigint();
   try{await embedding.detach();}catch(e){if(scenario==='close-failure')assert.equal(e.message,'INJECTED_CLOSE_FAILURE');else assert.equal(e.code,'CLEANUP_UNCONFIRMED');}
   await closed;await tick();await tick();
   if(scenario==='close-failure'){
    assert.equal(embedding.checkCleanup(),false);assert.throws(()=>embedding.attach(ctx,port),e=>e.code==='APPLICATION_CONNECTION_OWNED');
   }else assert.equal(embedding.checkCleanup(),true);
   assert.equal(closeCalls,1);assert.equal(channel.stats().inflight,0);assert.deepEqual(fingerprint(),before);
   const state=embedding.current;assert.equal(state.dispatchAttempted,true);assert.equal(state.pendingStore,0);assert.equal(state.pendingRequests,0);
   const m=measure(fds.slice(used));m.pendingStore=state.pendingStore;m.pendingRequests=state.pendingRequests;m.inflight=channel.stats().inflight;
   send({kind:'done',round,node:m,code,lifecycle:state.lifecycle,readonly_unchanged:true,close_calls:closeCalls,
         close_us:Number((process.hrtime.bigint()-shutdown)/1000n),duration_us:Number((process.hrtime.bigint()-started)/1000n),
         timeout_mode:scenario==='timeout'?'AFTER_ENTERED_CALLBACK_INJECTION':null});
  }finally{await channel.close();}
 }
}catch(e){console.error(e.stack);process.exitCode=1;}
finally{
 stream.close();for(const n of fds.slice(used)){try{fs.closeSync(n);}catch{}}
}
