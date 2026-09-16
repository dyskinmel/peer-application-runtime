import {EventCommands,EventSubscription} from '../../../product/wp10/lib/index.js';
import type {CommandContext,EventCommandChannel,PublishCommand,EventHostChannel,PublishResult} from '../../../product/wp10/lib/index.js';
import {ConnectedCommandChannel} from '../../../product/wp10/node/command-channel.mjs';
declare const socket:unknown;declare const ctx:CommandContext;declare const subscription:EventHostChannel;
const channel:EventCommandChannel=new ConnectedCommandChannel(socket,{expectedContext:ctx});
const commands=new EventCommands(channel,ctx,'aa'.repeat(16));
const input:PublishCommand={operationId:'bb'.repeat(16),payload:{count:{kind:'uint64',value:'18446744073709551615'}},parents:[]};
const result:PublishResult=await commands.publish(input);
if(result.kind==='local-committed'){
 const sequence:string=result.sequence;
 const remote:false=result.replicated;
 // @ts-expect-error local receipt cannot be promoted to remote durability
 const replicated:true=result.replicated;
}
// @ts-expect-error uint64 wire input is a canonical string, never Number
await commands.publish({operationId:'bb',payload:{count:{kind:'uint64',value:42}},parents:[]});
// @ts-expect-error subscription channel cannot gain a publish operation
subscription.request('publish',input,new AbortController().signal);
// @ts-expect-error command channel cannot accept an ACK operation
channel.request('ack',{},new AbortController().signal);
// @ts-expect-error command channel is not a subscription owner port
await EventSubscription.connect(channel,ctx);
await commands.inquire('bb'.repeat(16));commands.close();
