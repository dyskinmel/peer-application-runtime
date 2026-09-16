import net from 'node:net';import assert from 'node:assert/strict';
import {ConnectedApplicationChannel} from '../../../product/wp11/node/application-channel.mjs';
import {LocalCallerIntent} from '../../../product/wp11/node/caller-intent.mjs';
import {ApplicationOwnerClient} from '../../../product/wp11/lib/application-owner.js';
const[fd,contextText,targetsText,directory,mode]=process.argv.slice(2);const context=JSON.parse(contextText),targets=JSON.parse(targetsText);
const channel=new ConnectedApplicationChannel(new net.Socket({fd:Number(fd),readable:true,writable:true}),{expectedContext:context,requestTimeoutMs:10000,helloTimeoutMs:10000});
let client;let stopped=null;
try{
 await channel.ready;client=new ApplicationOwnerClient(context,channel,new LocalCallerIntent(directory));
 if(mode==='recover'){await client.restore();await client.observe();await client.inquire();assert.equal(client.current.original.operationId,'6f'.repeat(16));}
 else if(mode==='readonly'){await client.observe();await assert.rejects(client.prepare('6f'.repeat(16),0,targets));}
 else{
  await client.observe();
  if(mode==='kill-prepare'){await assert.rejects(client.prepare('6f'.repeat(16),0,targets));stopped='prepare';}
  else{
   await client.prepare('6f'.repeat(16),0,targets);
   if(['kill-dispatch','kill-commit'].includes(mode)){await assert.rejects(client.dispatch());stopped='dispatch';}
   else{
    await client.dispatch();
    if(mode==='blocked')assert.equal(client.current.snapshot.journal.operationState,'CORE_BLOCKED');
    else if(mode==='kill-retire'){await assert.rejects(client.retire());stopped='retire';}
    else{await client.inquire();await client.retire();assert.equal(client.current.snapshot.journal.state,'RETIRED');}
   }
  }
 }
 const state=client.current;const stored=await new LocalCallerIntent(directory).load();await client.close();
 console.log(JSON.stringify({state,stored,stopped,channel:channel.stats()}));
}catch(e){console.error(e.stack);process.exitCode=1;}finally{await client?.close();await channel.close();}
