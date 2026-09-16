/** Public synthetic keys, private connected fds, real SQLite; no external service. */
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {EventCommandClient,EventSubscription} from '../product/wp10/lib/index.js';
import {presentLocalEventClient} from '../product/wp11/lib/index.js';
process.env.PAR_ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {start,publication,operation}=await import('../tests/product/event-host/command_integration.mjs');
const root=await mkdtemp(path.join(tmpdir(),'par-client-demo-'));const workers=[];let client,subscription;
try{
 let worker=await start(root,'kill-commit');workers.push(worker);
 client=new EventCommandClient(worker.info.commandContext);
 client.rebind(worker.commandChannel,worker.hello.context,worker.hello.hostId);
 const unknown=await client.publish(publication());assert.equal(unknown.kind,'outcome-unknown');
 assert.equal((await worker.exit).signal,'SIGKILL');
 const before=presentLocalEventClient(client,worker.info.commandContext,'ja');
 assert.equal(before.outcome,'outcome-unknown');assert.equal(before.controls.publish,false);
 const firstHost=worker.hello.hostId;await worker.stop();
 worker=await start(root);workers.push(worker);assert.notEqual(worker.hello.hostId,firstHost);
 client.rebind(worker.commandChannel,worker.hello.context,worker.hello.hostId);
 // Rebinding itself does not issue another publish, acknowledge, or even inquire.
 assert.equal(worker.info.journal.events,1);assert.equal(worker.info.journal.nonces,1);
 assert.equal(client.current.requiresInquiry,true);
 const result=await client.inquire(operation);assert.equal(result.kind,'local-committed');
 const after=presentLocalEventClient(client,worker.info.commandContext,'ja');
 assert.equal(after.sharedCommit,false);assert.equal(after.remoteProtection,false);
 subscription=await EventSubscription.connect(worker.port,worker.info.subscriptionContext);
 const delivery=await subscription.poll();assert.ok(delivery);assert.equal(delivery.events[0].eventId,result.eventId);
 assert.equal(subscription.lastCursor.position,'0');await delivery.ack();assert.equal(subscription.lastCursor.position,'1');
 await subscription.close();client.close();await client.waitForCleanup();await worker.stop();
 assert.equal(worker.ended.journal.events,1);assert.equal(worker.ended.journal.nonces,1);
 assert.equal(worker.ended.stats.commands.channels,0);assert.equal(worker.ended.stats.subscriptions.channels,0);
 assert.equal(client.current.cleanup.pending,0);assert.equal(client.current.cleanup.failed,false);
 console.log(JSON.stringify({scope:'REAL_LOCAL_SQLITE_PRIVATE_FD_SYNTHETIC_KEYS_NOT_NATIVE_OR_NETWORK',
  process_stop:'SIGKILL_AFTER_COMMIT',before:before.outcome,after:after.outcome,
  original_operation_id:operation,host_changed:firstHost!==worker.hello.hostId,
  journal_events:worker.ended.journal.events,reserved_nonces:worker.ended.journal.nonces,
  before_ack:'0',after_ack:'1',remaining_command_channels:0,remaining_subscription_channels:0,
  before_message_ja:before.message,after_message_ja:after.message,
  automatic_reconnect:false,automatic_retry:false,automatic_ack:false,shared_document_commit:false,
  remote_protection:false,production_ready:false},null,2));
}finally{
 if(subscription)await subscription.close();
 if(client){client.close();await client.waitForCleanup()}
 for(const worker of workers)await worker.stop();
 await rm(root,{recursive:true,force:true});
}
