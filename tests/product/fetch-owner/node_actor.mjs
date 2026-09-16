import net from 'node:net';import assert from 'node:assert/strict';
import {ConnectedFetchChannel} from '../../../product/wp11/node/fetch-channel.mjs';
import {FetchOwnerClient} from '../../../product/wp11/lib/fetch-owner.js';
const [fd,pinText,mode,oldDigest]=process.argv.slice(2);const pin=JSON.parse(pinText);
const channel=new ConnectedFetchChannel(new net.Socket({fd:Number(fd),readable:true,writable:true}),{expectedContext:pin,requestTimeoutMs:4000});
let client;const actions=[];let stopped=null;
try{
 await channel.ready;client=new FetchOwnerClient(pin,channel);await client.observe();actions.push('observe');
 if(mode==='readonly'){
  await assert.rejects(()=>channel.request('propose',{context:pin,expectedRevision:client.current.snapshot.observation.revision},new AbortController().signal),/OWNER_OPERATION_DENIED/);
 }else if(mode==='cancel'||mode==='deadline'){
  const a=new AbortController();let timer;
  if(mode==='cancel')timer=setTimeout(()=>a.abort(),100);
  try{await assert.rejects(()=>client.propose({signal:a.signal,timeoutMs:mode==='deadline'?50:1000}));}finally{clearTimeout(timer);}
  assert.equal(client.current.status,'UNAVAILABLE');stopped=client.current.reason;
 }else if(mode==='resume'){
  await client.resume(oldDigest);actions.push('resume');assert.equal(client.current.snapshot.progress.stored,1);
  await client.fetch();actions.push('fetch'); // Existing bytes only, no provider required.
 }else{
  for(let n=0;n<(mode==='rounds'?2:1);n++){
   await client.propose();actions.push('propose');
   if(mode==='kill-accept'){
    await assert.rejects(()=>client.accept());stopped=client.current.reason;break;
   }
   await client.accept();actions.push('accept');
   if(mode==='kill-fetch'){
    await assert.rejects(()=>client.fetch());stopped=client.current.reason;break;
   }
   await client.fetch();actions.push('fetch');
  }
  if(!stopped){await client.validate();actions.push('validate');}
 }
 const saved=client.current;const digest=saved.originalPlanDigest;
 assert.equal(saved.snapshot?.observation.applied??false,false);
 await client.close();assert.equal(channel.stats().inflight,0);
 console.log(JSON.stringify({result:'PASS',actions,stopped,planDigest:digest,state:saved,channel:channel.stats()}));
}catch(e){console.error(e.stack);process.exitCode=1;}finally{await client?.close();await channel.close();}
