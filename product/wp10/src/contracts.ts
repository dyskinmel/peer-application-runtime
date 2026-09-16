/** Local owner-injected interface. Values are not cryptographic attestations. */
export type Decimal = string;
export type Kind = 'text'|'uint64'|'int64'|'bool'|'bytes';
export interface EventContext {
  readonly protocol: 'par-sdk-events-local-0038';
  readonly appId: string; readonly spaceId: string; readonly streamId: string;
  readonly epoch: Decimal; readonly schema: Readonly<Record<string,Kind>>;
  readonly schemaDigest: string; readonly issuer: string; readonly consumerId: string;
  readonly journalGeneration: string;
}
export interface Cursor {
  readonly position: Decimal; readonly revision: Decimal;
  readonly eventId: string|null; readonly token: string;
}
export interface OwnerEventPort {
  open(request: {context:EventContext; expectedCursor:Cursor|null}, signal:AbortSignal):Promise<unknown>;
  poll(request:{sessionId:string;limit:number;byteLimit:number}, signal:AbortSignal):Promise<unknown>;
  ack(request:{sessionId:string;token:string}, signal:AbortSignal):Promise<unknown>;
  cursorRead(request:{sessionId:string}, signal:AbortSignal):Promise<unknown>;
  cancel(request:{sessionId:string}, signal:AbortSignal):Promise<unknown>;
  /** Must wait without spinning; wake on potential new data/authority changes.
   * Lost wakeups must be avoided by the host. No event/cursor may be dropped. */
  wait(signal:AbortSignal):Promise<void>;
}
export interface EventValue {
  readonly sequence:bigint; readonly eventId:string; readonly operationId:string;
  readonly parents:ReadonlyArray<string>;
  readonly payload:Readonly<Record<string,string|bigint|boolean|Readonly<{hex:string}>>>;
}
export interface Delivery { readonly events:ReadonlyArray<EventValue>; readonly hasMore:boolean; ack():Promise<Cursor>; }
export interface ConnectOptions {
  readonly signal?:AbortSignal; readonly expectedCursor?:Cursor;
  readonly limit?:number; readonly byteLimit?:number; readonly cleanupTimeoutMs?:number;
}
export class EventBindingError extends Error {
  constructor(readonly code:string){super(code);this.name='EventBindingError';}
}
export const fail=(code='PORT_INVALID'):never=>{throw new EventBindingError(code)};
export function need(ok:unknown,code='PORT_INVALID'):asserts ok {if(!ok)fail(code);}
export const u64=(v:unknown):bigint=>{
  need(typeof v==='string' && /^(0|[1-9][0-9]{0,19})$/.test(v));
  const n=BigInt(v);need(n<=18446744073709551615n);return n;
};
export const i64=(v:unknown):bigint=>{
  need(typeof v==='string'&&/^(0|-?[1-9][0-9]{0,18}|-?[1-9][0-9]{19})$/.test(v));
  const n=BigInt(v);need(n>=-9223372036854775808n&&n<=9223372036854775807n);return n;
};
export function hex(v:unknown,bytes?:number,maxBytes=4096):string {
  need(typeof v==='string' && v.length<=maxBytes*2 && v.length%2===0 && /^[0-9a-f]*$/.test(v));
  need(bytes===undefined?v.length>0:v.length===bytes*2);return v;
}
/** Reject accessors/custom prototypes before traversal. Not a JS Proxy sandbox. */
export function copyData(value:unknown,maxBytes=1500000):unknown {
 let nodes=0,bytes=0;const stack=new Set<object>();
 const visit=(v:unknown,depth:number):unknown=>{
  need(++nodes<=12000&&depth<=10);if(v===null||typeof v==='boolean')return v;
  if(typeof v==='string'){bytes+=new TextEncoder().encode(v).length;need(bytes<=maxBytes);need(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(v));return v;}
  if(typeof v==='number'){need(Number.isSafeInteger(v));return v;}
  need(typeof v==='object'&&v!==null&&!stack.has(v));stack.add(v);
  const arr=Array.isArray(v),proto=Object.getPrototypeOf(v);
  need(arr?proto===Array.prototype:(proto===Object.prototype||proto===null));
  const keys=Reflect.ownKeys(v);need(keys.length<=4096);
  const out:Record<string,unknown>|unknown[]=arr?[]:Object.create(null);
  if(arr){need(v.length<=4096);need(keys.length===v.length+1);}
  for(const key of keys){
   need(typeof key==='string');const d=Object.getOwnPropertyDescriptor(v,key);need(d&&'value'in d);
   if(arr&&key==='length')continue;
   need(d.enumerable);if(arr)need(/^(0|[1-9][0-9]*)$/.test(key)&&Number(key)<v.length);
   bytes+=key.length;need(bytes<=maxBytes);
   Object.defineProperty(out,key,{value:visit(d.value,depth+1),enumerable:true,writable:true,configurable:true});
  }
  stack.delete(v);return out;
 };
 return visit(value,0);
}
export function obj(v:unknown,keys:ReadonlyArray<string>):Record<string,unknown>{
 need(typeof v==='object'&&v!==null&&!Array.isArray(v));const r=v as Record<string,unknown>;
 need(Object.keys(r).sort().join('|')===[...keys].sort().join('|'));return r;
}
export function same(a:unknown,b:unknown):boolean{
 const normalize=(v:unknown):unknown=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,normalize((v as Record<string,unknown>)[k])])):Array.isArray(v)?v.map(normalize):v;
 return JSON.stringify(normalize(a))===JSON.stringify(normalize(b));
}
export function cursor(v:unknown):Cursor{
 const r=obj(v,['position','revision','eventId','token']);const p=u64(r.position);u64(r.revision);
 need(p===0n?r.eventId===null:typeof r.eventId==='string');if(r.eventId!==null)hex(r.eventId,32);
 return Object.freeze({position:r.position as string,revision:r.revision as string,eventId:r.eventId as string|null,token:hex(r.token)});
}
export function context(v:unknown):EventContext{
 const r=obj(copyData(v,16384),['protocol','appId','spaceId','streamId','epoch','schema','schemaDigest','issuer','consumerId','journalGeneration']);
 need(r.protocol==='par-sdk-events-local-0038');need(typeof r.appId==='string'&&/^[a-z0-9][a-z0-9.-]{0,127}$/.test(r.appId));
 for(const k of ['spaceId','streamId','schemaDigest','issuer','journalGeneration'])hex(r[k],32);
 hex(r.consumerId,16);need(u64(r.epoch)>0n);need(typeof r.schema==='object'&&r.schema!==null&&!Array.isArray(r.schema));
 const schema=r.schema as Record<string,unknown>,keys=Object.keys(schema);need(keys.length>=1&&keys.length<=16);
 for(const k of keys)need(/^[a-z][a-z0-9_]{0,31}$/.test(k)&&['text','uint64','int64','bool','bytes'].includes(schema[k] as string));
 Object.freeze(schema);return Object.freeze(r) as unknown as EventContext;
}
export function response(v:unknown,expected:EventContext,session:string|undefined,kind:string,keys:string[]):Record<string,unknown>{
 const r=obj(copyData(v),['kind','context','sessionId',...keys]);need(r.kind===kind&&same(context(r.context),expected));hex(r.sessionId,16);
 if(session!==undefined)need(r.sessionId===session);return r;
}
export function payload(v:unknown,schema:Readonly<Record<string,Kind>>):{value:EventValue['payload'];rawMaterialBytes:number}{
 const r=obj(v,Object.keys(schema)),out:Record<string,string|bigint|boolean|Readonly<{hex:string}>>=Object.create(null);let raw=0;
 for(const key of Object.keys(schema)){
  const f=obj(r[key],['kind','value']);need(f.kind===schema[key]);const val=f.value;
  switch(f.kind){
   case 'uint64':out[key]=u64(val);break;
   case 'int64':out[key]=i64(val);break;
   case 'bool':need(typeof val==='boolean');out[key]=val;break;
   case 'text':need(typeof val==='string');raw+=new TextEncoder().encode(val).length;out[key]=val;break;
   case 'bytes':need(typeof val==='string'&&val.length<=32768&&val.length%2===0&&/^[0-9a-f]*$/.test(val));raw+=val.length/2;out[key]=Object.freeze({hex:val});break;
   default:fail();
  }
 }
 need(raw<=16384);return {value:Object.freeze(out),rawMaterialBytes:raw};
}
