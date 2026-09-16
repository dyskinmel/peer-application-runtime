import {EventBindingError,need,u64} from './contracts.js';
export interface Snapshot {readonly revision:bigint;readonly payload:Uint8Array;}
/** Capacity one; volatile state notifications, never a durable event stream. */
export class LatestSnapshots implements AsyncIterableIterator<Snapshot>{
 readonly #max:number;#revision:bigint|undefined;#payload:Uint8Array|undefined;#delivered:bigint|undefined;#closed=false;
 #waiter:((v:IteratorResult<Snapshot>)=>void)|undefined;
 constructor(options:{maxBytes?:number}={}){this.#max=options.maxBytes??65536;need(Number.isInteger(this.#max)&&this.#max>=1&&this.#max<=524288,'INVALID_OPTIONS');}
 publish(revision:string,payload:Uint8Array):void{
  need(!this.#closed,'CLOSED');const n=u64(revision);need(payload instanceof Uint8Array,'INVALID_PAYLOAD');need(payload.byteLength<=this.#max,'RESOURCE_LIMIT');
  if(this.#revision!==undefined){need(n>=this.#revision,'REVISION_ROLLBACK');if(n===this.#revision){need(payload.length===this.#payload!.length&&payload.every((b,i)=>b===this.#payload![i]),'REVISION_CONFLICT');return;}}
  this.#revision=n;this.#payload=new Uint8Array(payload);
  if(this.#waiter){const resolve=this.#waiter;this.#waiter=undefined;resolve(this.#take());}
 }
 #take():IteratorResult<Snapshot>{this.#delivered=this.#revision;return {done:false,value:Object.freeze({revision:this.#revision!,payload:new Uint8Array(this.#payload!)})};}
 [Symbol.asyncIterator]():AsyncIterableIterator<Snapshot>{return this;}
 async next():Promise<IteratorResult<Snapshot>>{
  if(this.#closed)return {done:true,value:undefined};need(!this.#waiter,'BUSY');
  if(this.#revision!==undefined&&this.#revision!==this.#delivered)return this.#take();
  return new Promise(resolve=>{this.#waiter=resolve;});
 }
 async return():Promise<IteratorResult<Snapshot>>{
  this.#closed=true;this.#payload=undefined;const resolve=this.#waiter;this.#waiter=undefined;
  const result={done:true as const,value:undefined};resolve?.(result);return result;
 }
 async throw(error?:unknown):Promise<IteratorResult<Snapshot>>{await this.return();throw error??new EventBindingError('CANCELLED');}
}
