/** Synthetic local demo: real SQLite and a dedicated connected socket, not network discovery. */
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {EventSubscription} from '../product/wp10/lib/index.js';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.env.PAR_ROOT=ROOT;
const commandMode=process.argv.includes('--commands');
const {start,publication,operation}=await import(commandMode?'../tests/product/event-host/command_integration.mjs':'../tests/product/event-host/integration.mjs');
const root=await mkdtemp(path.join(tmpdir(),'par-event-demo-'));let worker,subscription;
try{
 worker=await start(root,commandMode?'normal':'publish-on-wait');
 subscription=await EventSubscription.connect(worker.port,commandMode?worker.info.subscriptionContext:worker.info.context);
 assert.equal(await subscription.poll(),null);
 const waiting=subscription.next();
 let receipt,inquiry;
 if(commandMode){
  receipt=await worker.commands.publish(publication());
  assert.equal(receipt.kind,'local-committed');assert.equal(receipt.replicated,false);
  inquiry=await worker.commands.inquire(operation);assert.deepEqual(inquiry,receipt);
 }
 const delivery=(await waiting).value;
 assert.ok(delivery);assert.equal(subscription.lastCursor.position,'0');
 const exact=delivery.events[0].payload.count;
 await delivery.ack();assert.equal(subscription.lastCursor.position,'1');
 await subscription.close();await worker.stop();
 console.log(JSON.stringify({scope:'PUBLIC_SYNTHETIC_KEYS_REAL_LOCAL_SQLITE_DEDICATED_PRIVATE_FD',initial_poll:'EMPTY',notification:'OWNER_COMMITTED_AFTER_WAIT_REGISTRATION',received_event_count:delivery.events.length,exact_u64:String(exact),before_ack:'0',after_ack:'1',remaining_waiters:(commandMode?worker.ended.stats.subscriptions:worker.ended.stats).waiters,remaining_channels:(commandMode?worker.ended.stats.subscriptions:worker.ended.stats).channels,...(commandMode?{command_result:receipt.kind,inquiry_result:inquiry.kind,operation_id:receipt.operationId,remote_durability:receipt.replicated,automatic_retry:false,remaining_command_channels:worker.ended.stats.commands.channels}:{}),automatic_ack:false,production_ready:false},null,2));
}finally{
 if(subscription)await subscription.close();
 if(worker)await worker.stop();
 await rm(root,{recursive:true,force:true});
}
