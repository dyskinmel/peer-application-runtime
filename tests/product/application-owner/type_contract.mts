import {ApplicationOwnerClient,type ApplicationContext,type ApplicationOwnerPort,type CallerIntentStore} from '../../../product/wp11/lib/application-owner.js';
import {LocalCallerIntent} from '../../../product/wp11/node/caller-intent.mjs';
import {ConnectedApplicationChannel} from '../../../product/wp11/node/application-channel.mjs';
declare const context:ApplicationContext;declare const port:ApplicationOwnerPort;
const store:CallerIntentStore=new LocalCallerIntent('/owner/enrolled/private-slot');
const client=new ApplicationOwnerClient(context,port,store);void client;
const wire:ApplicationOwnerPort=new ConnectedApplicationChannel({}, {expectedContext:context});void wire;
// @ts-expect-error caller durability port is required
new ApplicationOwnerClient(context,port);
// @ts-expect-error publish is not part of this profile
port.request('publish',{},new AbortController().signal);
// @ts-expect-error targets must be explicitly supplied
client.prepare('6f'.repeat(16),0);
