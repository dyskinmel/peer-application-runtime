import {GenerationEventPort,EventSubscription} from '../../../product/wp10/lib/index.js';
import type {EventHostChannel,OwnerEventPort,EventContext} from '../../../product/wp10/lib/index.js';
import {ConnectedEventChannel} from '../../../product/wp10/node/channel.mjs';
declare const rawSocket:unknown;declare const ctx:EventContext;
const channel:EventHostChannel=new ConnectedEventChannel(rawSocket,{expectedContext:ctx});
const port:OwnerEventPort=new GenerationEventPort(channel,'aa'.repeat(16));
const sub=await EventSubscription.connect(port,ctx);
// @ts-expect-error public owner subscription channel does not expose publication
channel.request('publish',{},new AbortController().signal);
// @ts-expect-error wake tickets are not durable cursors or event acknowledgments
port.ack({sessionId:'aa',ticket:{hostId:'aa',revision:'1'}},new AbortController().signal);
for await(const delivery of sub){await delivery.ack();break}
