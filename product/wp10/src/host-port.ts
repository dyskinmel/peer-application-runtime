/** Owner-supplied private channel. A wake ticket is not a durable cursor/proof. */
import {copyData, obj, need, hex, u64, EventBindingError} from './contracts.js';
import type {OwnerEventPort, EventContext, Cursor} from './contracts.js';
export type HostOperation = 'open'|'poll'|'ack'|'cursor'|'cancel'|'wait';
export interface EventHostChannel {
  request(operation:HostOperation, args:unknown, signal:AbortSignal):Promise<unknown>;
  close():Promise<void>;
}
export interface WakeTicket {readonly hostId:string; readonly revision:string;}

export class GenerationEventPort implements OwnerEventPort {
  readonly #channel:EventHostChannel; readonly #hostId:string;
  #session:string|undefined; #revision=0n; #empty:WakeTicket|undefined;
  constructor(channel:EventHostChannel, trustedHostId:string){
    need(typeof channel?.request==='function'&&typeof channel?.close==='function','INVALID_PORT');
    this.#channel=channel;this.#hostId=hex(trustedHostId,16);
  }
  async #call(op:HostOperation,args:unknown,signal:AbortSignal):Promise<{result:unknown;ticket:WakeTicket}>{
    if(signal.aborted)throw new EventBindingError('CANCELLED');
    const raw=await this.#channel.request(op,copyData(args,65536),signal);
    if(signal.aborted)throw new EventBindingError('CANCELLED');
    const r=obj(copyData(raw),['protocol','ticket','result']);need(r.protocol==='par-owner-event-host-0039');
    const t=obj(r.ticket,['hostId','revision']);need(hex(t.hostId,16)===this.#hostId);
    const rev=u64(t.revision);need(rev>=this.#revision);this.#revision=rev;
    return {result:r.result,ticket:Object.freeze({hostId:this.#hostId,revision:t.revision as string})};
  }
  async open(r:{context:EventContext;expectedCursor:Cursor|null},s:AbortSignal):Promise<unknown>{
    const out=await this.#call('open',r,s);
    const value=obj(out.result,['kind','context','sessionId','cursor']);need(value.kind==='opened');
    this.#session=hex(value.sessionId,16);return out.result;
  }
  async poll(r:{sessionId:string;limit:number;byteLimit:number},s:AbortSignal):Promise<unknown>{
    this.#empty=undefined;
    const out=await this.#call('poll',r,s);
    const v=obj(out.result,['kind','context','sessionId','cursor','events','ackToken','hasMore']);
    need(v.kind==='batch'&&Array.isArray(v.events)&&v.sessionId===this.#session);
    if(v.events.length===0){need(v.ackToken===null&&v.hasMore===false);this.#empty=out.ticket;}
    return out.result;
  }
  async ack(r:{sessionId:string;token:string},s:AbortSignal):Promise<unknown>{
    this.#empty=undefined;return (await this.#call('ack',r,s)).result;
  }
  async cursorRead(r:{sessionId:string},s:AbortSignal):Promise<unknown>{
    // Crucial: a later observation must NOT replace the empty-poll ticket.
    return (await this.#call('cursor',r,s)).result;
  }
  async cancel(r:{sessionId:string},s:AbortSignal):Promise<unknown>{
    this.#empty=undefined;return (await this.#call('cancel',r,s)).result;
  }
  async wait(s:AbortSignal):Promise<void>{
    need(this.#empty&&this.#session,'WAKE_TICKET_REQUIRED');
    const ticket=this.#empty;this.#empty=undefined;
    const out=await this.#call('wait',{sessionId:this.#session,ticket},s);
    const r=obj(out.result,['kind','reason']);need(r.kind==='wake');
    need(r.reason==='changed'?u64(out.ticket.revision)>u64(ticket.revision):r.reason==='deadline'&&out.ticket.revision===ticket.revision);
    // This is only permission to poll again; never an event or acknowledgment.
  }
}
