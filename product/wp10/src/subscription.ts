import {EventBindingError,fail,need,hex,u64,context,cursor,payload,response,same,copyData,obj} from './contracts.js';
import type {ConnectOptions,Cursor,Delivery,EventContext,EventValue,OwnerEventPort} from './contracts.js';
type Pending={token:string;events:ReadonlyArray<EventValue>;hasMore:boolean;end:bigint;eventId:string;fingerprint:unknown;delivery?:Delivery;acknowledged?:Cursor};

/** Pull-based, bounded batches. Successful iteration is never acknowledgment. */
export class EventSubscription implements AsyncIterableIterator<Delivery> {
 readonly #port:OwnerEventPort; readonly #context:EventContext;readonly #controller=new AbortController();
 readonly #limit:number;readonly #byteLimit:number;readonly #cleanupTimeout:number;
 #session:string|undefined; #cursor:Cursor|undefined; #pending:Pending|undefined;#last:Pending|undefined;
 #busy=false; #state='OPEN'; #closePromise:Promise<void>|undefined;
 #external:AbortSignal|undefined;#externalListener:(()=>void)|undefined;
 private constructor(port:OwnerEventPort,expected:EventContext,options:ConnectOptions){
  this.#port=port;this.#context=context(expected);
  for(const method of ['open','poll','ack','cursorRead','cancel','wait'] as const)need(typeof port[method]==='function','INVALID_PORT');
  this.#limit=options.limit??16;this.#byteLimit=options.byteLimit??262144;this.#cleanupTimeout=options.cleanupTimeoutMs??1000;
  for (const [v, lo, hi] of [[this.#limit,1,32], [this.#byteLimit,1,524288], [this.#cleanupTimeout,10,10000]] as const) {
    need(Number.isInteger(v) && v >= lo && v <= hi, 'INVALID_OPTIONS');
  }
  this.#external=options.signal;
  if(this.#external){this.#externalListener=()=>{void this.close().catch(()=>{});};this.#external.addEventListener('abort',this.#externalListener,{once:true});}
 }
 static async connect(port:OwnerEventPort,expected:EventContext,options:ConnectOptions={}):Promise<EventSubscription>{
  if(options.signal?.aborted)fail('CANCELLED');
  const s=new EventSubscription(port,expected,options);
  try{
   const pin=options.expectedCursor===undefined?null:cursor(copyData(options.expectedCursor));
   const operation=Promise.resolve().then(()=>{if(s.#controller.signal.aborted)fail('CANCELLED');return port.open({context:s.#context,expectedCursor:pin},s.#controller.signal);}).then(raw=>{
    const r=response(raw,s.#context,undefined,'opened',['cursor']);s.#session=r.sessionId as string;
    // An owner may have opened even after local cancellation. Always release
    // a valid late session; never surface late data to the cancelled caller.
    if(s.#controller.signal.aborted){void s.#cleanup(s.#session).catch(()=>{});fail('CANCELLED');}
    const c=cursor(r.cursor);
    if(pin){need(u64(c.position)>=u64(pin.position)&&u64(c.revision)>=u64(pin.revision),'CURSOR_ROLLBACK');if(c.position===pin.position)need(c.eventId===pin.eventId&&c.revision===pin.revision&&c.token===pin.token,'CURSOR_ROLLBACK');}
    s.#cursor=c;return s;
   });
   const result=await s.#race(operation);if(s.#controller.signal.aborted)fail('CANCELLED');return result;
  }catch(e){void s.close().catch(()=>{});if(e instanceof EventBindingError)throw e;throw new EventBindingError('PORT_FAILED');}
 }
 get state():string{return this.#state;}
 get lastCursor():Cursor{need(this.#cursor,'NOT_OPEN');return Object.freeze({...this.#cursor});}
 [Symbol.asyncIterator]():AsyncIterableIterator<Delivery>{return this;}
 #enter():void{if(this.#state==='CLOSED')fail('CANCELLED');need(this.#state==='OPEN','RECONNECT_REQUIRED');need(!this.#busy,'BUSY');this.#busy=true;}
 #race<T>(p:Promise<T>):Promise<T>{
  const signal=this.#controller.signal;
  return new Promise<T>((resolve,reject)=>{
   const abort=()=>{signal.removeEventListener('abort',abort);reject(new EventBindingError('CANCELLED'));};
   if(signal.aborted){p.catch(()=>{});abort();return;}
   signal.addEventListener('abort',abort,{once:true});
   p.then(v=>{signal.removeEventListener('abort',abort);if(signal.aborted)abort();else resolve(v);},e=>{signal.removeEventListener('abort',abort);reject(signal.aborted?new EventBindingError('CANCELLED'):e);});
  });
 }
 async #call(fn:()=>Promise<unknown>):Promise<unknown>{
  if(this.#controller.signal.aborted)fail('CANCELLED');
  // Invoke synchronously: once called an effect may have happened even if the
  // promise rejects or the owner ignores cancellation.
  return this.#race(Promise.resolve(fn()));
 }
 async #poll():Promise<Delivery|null>{
  need(this.#session&&this.#cursor,'NOT_OPEN');
  const raw=await this.#call(()=>this.#port.poll({sessionId:this.#session!,limit:this.#limit,byteLimit:this.#byteLimit},this.#controller.signal));
  if(this.#controller.signal.aborted)fail('CANCELLED');
  const r=response(raw,this.#context,this.#session,'batch',['cursor','events','ackToken','hasMore']);
  need(same(cursor(r.cursor),this.#cursor));need(Array.isArray(r.events)&&r.events.length<=this.#limit&&typeof r.hasMore==='boolean');
  if(r.events.length===0){need(r.ackToken===null&&r.hasMore===false&&!this.#pending);return null;}
  const token=hex(r.ackToken),events:EventValue[]=[],ids=new Set<string>(),ops=new Set<string>();let total=0;
  for(const [i,value]of r.events.entries()){
   const e=obj(value,['sequence','eventId','operationId','parents','payload','payloadBytes']);
   const seq=u64(e.sequence);need(seq===u64(this.#cursor.position)+BigInt(i)+1n);
   const id=hex(e.eventId,32),op=hex(e.operationId,16);need(!ids.has(id)&&!ops.has(op));ids.add(id);ops.add(op);
   need(Array.isArray(e.parents)&&e.parents.length<=16);const parents=e.parents.map(p=>hex(p,32));need(new Set(parents).size===parents.length&&!parents.includes(id));
   const data=payload(e.payload,this.#context.schema);
   need(typeof e.payloadBytes==='number'&&Number.isInteger(e.payloadBytes)&&e.payloadBytes>=1&&e.payloadBytes<=16384&&data.rawMaterialBytes<=e.payloadBytes);total+=e.payloadBytes;need(total<=this.#byteLimit);
   events.push(Object.freeze({sequence:seq,eventId:id,operationId:op,parents:Object.freeze(parents),payload:data.value}));
  }
  if(this.#pending){need(same(this.#pending.fingerprint,r));return this.#pending.delivery!;}
  const last=events[events.length-1]!;
  const p:Pending={token,events:Object.freeze(events),hasMore:r.hasMore,end:last.sequence,eventId:last.eventId,fingerprint:r};
  p.delivery=Object.freeze({events:p.events,hasMore:p.hasMore,ack:()=>this.#ack(p)});this.#last=undefined;this.#pending=p;return p.delivery;
 }
 async poll():Promise<Delivery|null>{
  this.#enter();try{return await this.#poll();}catch(e){return this.#pollFailure(e);}finally{this.#busy=false;}
 }
 #pollFailure(e:unknown):never{
  if(this.#state!=='CLOSED')this.#state='RECONNECT_REQUIRED';this.#pending=undefined;
  throw e instanceof EventBindingError?e:new EventBindingError('PORT_FAILED');
 }
 async next():Promise<IteratorResult<Delivery>>{
  if(this.#state==='CLOSED')return {done:true,value:undefined};
  need(!this.#pending,'ACK_REQUIRED');this.#enter();
  try{
   while(true){
    const b=await this.#poll();if(b)return {done:false,value:b};
    await this.#call(()=>this.#port.wait(this.#controller.signal));
    // A spurious/immediately completed host notification must not create a
    // microtask spin. Only one waiting request exists; no prefetch while yielded.
    await this.#delay(25);
   }
  }catch(e){if(this.#state==='CLOSED'&&e instanceof EventBindingError&&e.code==='CANCELLED')return {done:true,value:undefined};return this.#pollFailure(e);}finally{this.#busy=false;}
 }
 #delay(ms:number):Promise<void>{
  return new Promise((resolve,reject)=>{
   const signal=this.#controller.signal;
   const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(new EventBindingError('CANCELLED'));};
   const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);
   if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});
  });
 }
 async #ack(p:Pending):Promise<Cursor>{
  this.#enter();
  try{
   if(p!==this.#pending){need(p===this.#last&&this.#pending===undefined&&p.acknowledged,'STALE_DELIVERY');return p.acknowledged;}
   const before=this.#cursor!;
   let result:Cursor;
   try{
    const raw=await this.#call(()=>this.#port.ack({sessionId:this.#session!,token:p.token},this.#controller.signal));
    if(this.#controller.signal.aborted)fail('CANCELLED');
    const r=response(raw,this.#context,this.#session,'acked',['cursor']);result=cursor(r.cursor);
    need(u64(result.position)===p.end&&result.eventId===p.eventId&&u64(result.revision)===u64(before.revision)+1n&&result.token!==before.token);
   }catch{
    if(this.#state!=='CLOSED')this.#state='ACK_OUTCOME_UNKNOWN';this.#pending=undefined;throw new EventBindingError('ACK_OUTCOME_UNKNOWN');
   }
   this.#cursor=result;p.acknowledged=result;this.#last=p;this.#pending=undefined;return result;
  }finally{this.#busy=false;}
 }
 async checkpoint():Promise<Cursor>{
  this.#enter();try{
   const raw=await this.#call(()=>this.#port.cursorRead({sessionId:this.#session!},this.#controller.signal));
   if(this.#controller.signal.aborted)fail('CANCELLED');
   const r=response(raw,this.#context,this.#session,'cursor',['cursor']);
   const c=cursor(r.cursor);need(same(c,this.#cursor));return c;
  }catch(e){return this.#pollFailure(e);}finally{this.#busy=false;}
 }
 async #cleanup(session:string):Promise<void>{
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
  try{
   const timeout=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new EventBindingError('CANCEL_OUTCOME_UNKNOWN'));},this.#cleanupTimeout);});
   const op=Promise.resolve().then(()=>this.#port.cancel({sessionId:session},controller.signal));
   response(await Promise.race([op,timeout]),this.#context,session,'cancelled',[]);
  }catch{throw new EventBindingError('CANCEL_OUTCOME_UNKNOWN');}finally{if(timer!==undefined)clearTimeout(timer);controller.abort();}
 }
 close():Promise<void>{
  if(this.#closePromise)return this.#closePromise;
  this.#state='CLOSED';this.#pending=undefined;this.#last=undefined;
  if(this.#external&&this.#externalListener)this.#external.removeEventListener('abort',this.#externalListener);
  this.#controller.abort();
  this.#closePromise=this.#session?this.#cleanup(this.#session):Promise.resolve();return this.#closePromise;
 }
 async return():Promise<IteratorResult<Delivery>>{await this.close();return {done:true,value:undefined};}
 async throw(error?:unknown):Promise<IteratorResult<Delivery>>{try{await this.close();}finally{throw error;}}
}
