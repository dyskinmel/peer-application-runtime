import {EventCommandClient} from '../../../product/wp10/lib/index.js';
import type {CommandContext,OwnedEventCommandChannel,EventClientSnapshot,EventClientView,PublishCommand} from '../../../product/wp10/lib/index.js';
import {ConnectedCommandChannel} from '../../../product/wp10/node/command-channel.mjs';
declare const socket:unknown;declare const ctx:CommandContext;declare const input:PublishCommand;
const channel:OwnedEventCommandChannel=new ConnectedCommandChannel(socket,{expectedContext:ctx});
const client=new EventCommandClient(ctx);client.rebind(channel,ctx,'aa'.repeat(16));
const state:EventClientSnapshot=client.current;
const view:EventClientView=client.view;
const shared:false=view.sharedCommit;const remote:false=view.remoteProtection;
// @ts-expect-error no implicit elevation of a local event receipt to shared commit
const elevated:true=view.sharedCommit;
// @ts-expect-error local view has no note body
const body=view.payload;
// @ts-expect-error immutable current state
state.connection='connected';
// @ts-expect-error channel disposal is part of the ownership contract
client.rebind({request:async()=>({})},ctx,'aa'.repeat(16));
// @ts-expect-error no automatically retried operation
client.retry();
client.restoreUnknown(input);await client.inquire(input.operationId);
client.close();await client.waitForCleanup();

import {presentLocalEventClient} from '../../../product/wp11/lib/index.js';
const panel=presentLocalEventClient(client,ctx,'ja');
const local:false=panel.sharedCommit;
// @ts-expect-error local event status cannot masquerade as note document state
const doc=panel.document;
// @ts-expect-error no automatic replay control on the reference-app view
const retry=panel.controls.retry;
