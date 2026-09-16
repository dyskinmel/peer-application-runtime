import {FetchOwnerClient,mountFetchControls,type FetchOwnerPort} from '../../../product/wp11/lib/fetch-owner.js';
import type {FetchPin} from '../../../product/wp11/lib/fetch-observation.js';
import {mountReference} from '../../../product/wp11/lib/renderer.js';
declare const pin:FetchPin;declare const port:FetchOwnerPort;declare const root:HTMLElement;
const client=new FetchOwnerClient(pin,port);
void client.observe();void client.propose();void client.accept();void client.fetch();
void client.resume('a'.repeat(64));void client.validate();void client.inquire('a'.repeat(32),0);
const controls=mountFetchControls(root,client,'ja');controls.destroy();
mountReference(root,{}, {fetchOwner:client});
// @ts-expect-error No application write is exposed.
client.apply('forbidden');
// @ts-expect-error The transport operation set excludes apply.
port.request('apply',{},new AbortController().signal);
// @ts-expect-error Owner pin is immutable.
client.pin.scope.documentId='changed';
// @ts-expect-error Snapshot cannot claim an applied document.
const applied:true=client.current.snapshot!.observation.applied;
// @ts-expect-error No implicit retry option.
client.fetch({retry:true});
// @ts-expect-error No implicit durable intent acknowledgement.
client.current.resumeRequired=false;
