/** Separate profile over the existing private connected-descriptor channel. */
import {ConnectedPrivateChannel} from '../../wp10/node/framing.mjs';
import {FETCH_OWNER_PROTOCOL,FETCH_OWNER_OPERATIONS,validateFetchOwnerContext} from '../lib/fetch-owner.js';
export class ConnectedFetchChannel extends ConnectedPrivateChannel {
 constructor(socket,options){super(socket,options,{protocol:FETCH_OWNER_PROTOCOL,operations:FETCH_OWNER_OPERATIONS,context:validateFetchOwnerContext});}
}
