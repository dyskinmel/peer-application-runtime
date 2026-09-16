/** Subscription-only profile over a trusted preconnected descriptor. */
import {ConnectedPrivateChannel} from './framing.mjs';
import {context} from '../lib/contracts.js';
export class ConnectedEventChannel extends ConnectedPrivateChannel {
 constructor(socket,options){
  super(socket,options,{protocol:'par-owner-event-host-0039',
   operations:['open','poll','ack','cursor','cancel','wait'],context});
 }
}
