/** Private preconnected stream only; service selection is made by the embedding. */
import {ConnectedPrivateChannel} from '../../wp10/node/framing.mjs';
import {APPLICATION_OWNER_PROTOCOL,APPLICATION_OWNER_OPERATIONS,validateApplicationContext} from '../lib/application-owner.js';
export class ConnectedApplicationChannel extends ConnectedPrivateChannel {
 constructor(socket,options){super(socket,options,{protocol:APPLICATION_OWNER_PROTOCOL,operations:APPLICATION_OWNER_OPERATIONS,context:validateApplicationContext});}
}
