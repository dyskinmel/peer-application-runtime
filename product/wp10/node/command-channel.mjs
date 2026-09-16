/** Dedicated owner-granted local command profile. No listener or auto-replay. */
import {ConnectedPrivateChannel} from './framing.mjs';
import {commandContext,COMMAND_PROTOCOL} from '../lib/commands.js';
export class ConnectedCommandChannel extends ConnectedPrivateChannel {
 constructor(socket,options){
  super(socket,options,{protocol:COMMAND_PROTOCOL,operations:['publish','inquire'],context:commandContext});
 }
}
