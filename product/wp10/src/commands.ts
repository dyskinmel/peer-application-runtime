/** Dedicated local commands. No shared-document commit, ACK or automatic replay. */
import {EventBindingError,copyData,obj,need,hex,u64,payload,same} from './contracts.js';
import type {Kind,Decimal} from './contracts.js';

export const COMMAND_PROTOCOL='par-local-event-commands-0040' as const;
export type CommandOperation='publish'|'inquire';
export interface CommandContext {
 readonly protocol:typeof COMMAND_PROTOCOL;
 readonly appId:string; readonly spaceId:string; readonly streamId:string;
 readonly epoch:Decimal; readonly schema:Readonly<Record<string,Kind>>;
 readonly schemaDigest:string; readonly issuer:string; readonly journalGeneration:string;
 readonly authority:'owner-publish'|'inquire-only';
}
export type CommandField =
 | Readonly<{kind:'text'|'uint64'|'int64'|'bytes';value:string}>
 | Readonly<{kind:'bool';value:boolean}>;
export interface PublishCommand {
 readonly operationId:string;
 readonly payload:Readonly<Record<string,CommandField>>;
 readonly parents:ReadonlyArray<string>;
}
export interface EventCommandChannel {
 request(operation:CommandOperation,args:unknown,signal:AbortSignal):Promise<unknown>;
}
export interface LocalEventCommit {
 readonly kind:'local-committed'; readonly operationId:string;
 readonly eventId:string; readonly sequence:Decimal;
 readonly replicated:false; readonly cancellationRequested:boolean;
}
export interface CommandCancelled {
 readonly kind:'cancelled'; readonly operationId:string; readonly phase:'before-send'|'before-commit';
}
export interface CommandRejected {
 readonly kind:'rejected'; readonly operationId:string; readonly code:string;
}
export interface LocalOutcomeUnknown {
 readonly kind:'outcome-unknown'; readonly operationId:string; readonly code:'LOCAL_OUTCOME_UNKNOWN';
}
export interface LocalEventAbsent {readonly kind:'not-found-local';readonly operationId:string;}
export type PublishResult=LocalEventCommit|CommandCancelled|CommandRejected|LocalOutcomeUnknown;
export type InquiryResult=LocalEventCommit|CommandCancelled|CommandRejected|LocalEventAbsent;
type CommandResult=PublishResult|InquiryResult;

export function commandContext(value:unknown):CommandContext {
 const r=obj(copyData(value,16384),['protocol','appId','spaceId','streamId','epoch','schema','schemaDigest','issuer','journalGeneration','authority']);
 need(r.protocol===COMMAND_PROTOCOL);
 need(typeof r.appId==='string'&&/^[a-z0-9][a-z0-9.-]{0,127}$/.test(r.appId));
 for(const k of ['spaceId','streamId','schemaDigest','issuer','journalGeneration'])hex(r[k],32);
 need(u64(r.epoch)>0n);need(r.authority==='owner-publish'||r.authority==='inquire-only');
 need(r.schema!==null&&typeof r.schema==='object'&&!Array.isArray(r.schema));
 const schema=r.schema as Record<string,unknown>,keys=Object.keys(schema);need(keys.length>0&&keys.length<=16);
 for(const key of keys)need(/^[a-z][a-z0-9_]{0,31}$/.test(key)&&['text','uint64','int64','bool','bytes'].includes(schema[key] as string));
 Object.freeze(schema);return Object.freeze(r) as unknown as CommandContext;
}
/** Exact bounded copy for both direct commands and retained client input.
 * This validates data, not caller authority or persistence across process restart.
 */
export function publishCommand(value:unknown,context:CommandContext):PublishCommand {
 try {
  const r=obj(copyData(value,65536),['operationId','payload','parents']);hex(r.operationId,16);
  payload(r.payload,context.schema);
  need(Array.isArray(r.parents)&&r.parents.length<=16);
  for(const p of r.parents)hex(p,32);
  need(new Set(r.parents).size===r.parents.length);
  need(new TextEncoder().encode(JSON.stringify({...r,context})).length<=65536);
  const fields=r.payload as Record<string,unknown>;
  for(const field of Object.values(fields))Object.freeze(field);
  Object.freeze(fields);Object.freeze(r.parents);
  return Object.freeze(r) as unknown as PublishCommand;
 } catch {throw new EventBindingError('COMMAND_INPUT_INVALID')}
}
const rejected=(operationId:string,code:string):CommandRejected=>Object.freeze({kind:'rejected',operationId,code});
const unknown=(operationId:string):LocalOutcomeUnknown=>Object.freeze({kind:'outcome-unknown',operationId,code:'LOCAL_OUTCOME_UNKNOWN'});

/** An owner-injected port, or ConnectedCommandChannel over a private descriptor.
 * A failed/unknown exchange is terminal for this client: rebind explicitly before
 * inquiry/retry. Read-only not-found-local is an observation, never replay consent.
 * Programmer input errors reject with EventBindingError(COMMAND_INPUT_INVALID).
 * Operational outcomes are discriminated unions; none of them automatically ACK.
 */
export class EventCommands {
 readonly #channel:EventCommandChannel;
 readonly #context:CommandContext;
 readonly #hostId:string;
 readonly #timeout:number;
 #busy=false; #closed=false; #failed=false; #active:AbortController|undefined;
 constructor(channel:EventCommandChannel,expectedContext:CommandContext,hostId:string,
             options:{requestTimeoutMs?:number}={}) {
  need(typeof channel?.request==='function','INVALID_PORT');
  this.#channel=channel;this.#context=commandContext(expectedContext);this.#hostId=hex(hostId,16);
  const opts=copyData(options,1024) as Record<string,unknown>;
  obj(opts,Object.hasOwn(opts,'requestTimeoutMs')?['requestTimeoutMs']:[]);
  const timeout=opts.requestTimeoutMs??6000;
  need(typeof timeout==='number'&&Number.isInteger(timeout)&&timeout>=10&&timeout<=60000,'INVALID_OPTIONS');
  this.#timeout=timeout;
 }
 async publish(input:PublishCommand,options:{signal?:AbortSignal}={}):Promise<PublishResult> {
  const args={...publishCommand(input,this.#context),context:this.#context};
  const operationId=args.operationId as string;
  if(this.#context.authority!=='owner-publish')return rejected(operationId,'COMMAND_NOT_AUTHORIZED');
  return await this.#perform('publish',args,options.signal) as PublishResult;
 }
 async inquire(operationId:string,options:{signal?:AbortSignal}={}):Promise<InquiryResult> {
  try {hex(operationId,16)} catch {throw new EventBindingError('COMMAND_INPUT_INVALID')}
  return await this.#perform('inquire',{context:this.#context,operationId},options.signal) as InquiryResult;
 }
 async #perform(operation:CommandOperation,args:Record<string,unknown>,signal:AbortSignal|undefined):Promise<CommandResult> {
  const operationId=args.operationId as string;
  if(signal!==undefined)need(typeof signal.aborted==='boolean'&&typeof signal.addEventListener==='function'&&typeof signal.removeEventListener==='function','INVALID_OPTIONS');
  if(this.#closed)return rejected(operationId,'COMMAND_CLOSED');
  if(this.#failed)return rejected(operationId,'COMMAND_RECONCILIATION_REQUIRED');
  if(this.#busy)return rejected(operationId,'COMMAND_BUSY');
  if(signal?.aborted)return Object.freeze({kind:'cancelled',operationId,phase:'before-send'});
  this.#busy=true;
  const controller=new AbortController();this.#active=controller;
  const relay=()=>controller.abort();signal?.addEventListener('abort',relay,{once:true});
  let abort:()=>void=()=>{};
  const interrupted=new Promise<never>((_,reject)=>{abort=()=>reject(new EventBindingError('COMMAND_INTERRUPTED'));controller.signal.addEventListener('abort',abort,{once:true})});
  const timer=setTimeout(relay,this.#timeout);
  try {
   // Admission is synchronous from the client's perspective. From here any thrown
   // error could follow a native commit; don't guess from an exception's message.
   // A synchronous throw must not leave the abort Promise unobserved.
   // This handler consumes only rejection; the race still receives it.
   void interrupted.catch(()=>{});
   const request=this.#channel.request(operation,args,controller.signal);
   const value=await Promise.race([request,interrupted]);
   need(!controller.signal.aborted,'COMMAND_INTERRUPTED');
   const result=this.#response(operation,operationId,value);
   if(result.kind==='outcome-unknown')this.#failed=true;
   return result;
  } catch {
   this.#failed=true;controller.abort();
   return operation==='publish'?unknown(operationId):rejected(operationId,'INQUIRY_UNAVAILABLE');
  } finally {
   clearTimeout(timer);controller.signal.removeEventListener('abort',abort);
   signal?.removeEventListener('abort',relay);this.#active=undefined;this.#busy=false;
  }
 }
 #response(operation:CommandOperation,operationId:string,value:unknown):CommandResult {
  const r=copyData(value,65536) as Record<string,unknown>;
  need(r&&typeof r==='object'&&!Array.isArray(r));
  need(r.hostId===this.#hostId&&r.operationId===operationId&&same(commandContext(r.context),this.#context));
  const base=['context','hostId','operationId','kind'];
  switch(r.kind){
   case 'local-committed':
    obj(r,[...base,'sequence','eventId','replicated','cancellationRequested']);
    need(u64(r.sequence)>0n);hex(r.eventId,32);need(r.replicated===false&&typeof r.cancellationRequested==='boolean');
    return Object.freeze({kind:'local-committed',operationId,sequence:r.sequence as string,eventId:r.eventId as string,replicated:false,cancellationRequested:r.cancellationRequested});
   case 'rejected':
    obj(r,[...base,'code']);need(typeof r.code==='string'&&/^[A-Z][A-Z0-9_]{0,63}$/.test(r.code));
    need(!['LOCAL_OUTCOME_UNKNOWN','EVENT_OUTCOME_UNKNOWN'].includes(r.code));
    return rejected(operationId,r.code);
   case 'cancelled':
    obj(r,[...base,'phase']);need(operation==='publish'&&r.phase==='before-commit');
    return Object.freeze({kind:'cancelled',operationId,phase:'before-commit'});
   case 'outcome-unknown':
    obj(r,[...base,'code']);need(operation==='publish'&&r.code==='LOCAL_OUTCOME_UNKNOWN');
    return unknown(operationId);
   case 'not-found-local':
    obj(r,base);need(operation==='inquire');return Object.freeze({kind:'not-found-local',operationId});
   default:throw new EventBindingError('COMMAND_RESPONSE_INVALID');
  }
 }
 /** Stop this client; the embedding still owns and explicitly closes its channel. */
 close():void {this.#closed=true;this.#active?.abort();}
 stats():Readonly<{closed:boolean;busy:boolean;reconciliationRequired:boolean}> {
  return Object.freeze({closed:this.#closed,busy:this.#busy,reconciliationRequired:this.#failed});
 }
}
