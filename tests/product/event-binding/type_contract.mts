import {EventSubscription, LatestSnapshots} from '../../../product/wp10/lib/index.js';
import type {OwnerEventPort, EventContext, Cursor, Delivery} from '../../../product/wp10/lib/index.js';
declare const port:OwnerEventPort;
declare const expected:EventContext;
declare const delivery:Delivery;
declare const cursor:Cursor;
const stream:AsyncIterable<Delivery>=await EventSubscription.connect(port,expected,{expectedCursor:cursor,limit:2});
for await(const batch of stream){const seq:bigint=batch.events[0]!.sequence;await batch.ack();break;}
// @ts-expect-error exact sequence is not a number
const unsafe:number=delivery.events[0]!.sequence;
// @ts-expect-error immutable array
delivery.events.push(delivery.events[0]!);
// @ts-expect-error cursor position is decimal string, not number
const invalid:Cursor={position:3,revision:'1',eventId:null,token:'aa'};
// @ts-expect-error no hidden ack API on iterator; acknowledgment requires delivery
(await EventSubscription.connect(port,expected)).ack();
const latest=new LatestSnapshots();latest.publish('18446744073709551615',new Uint8Array());
// @ts-expect-error snapshots do not have acknowledgment
latest.ack();
