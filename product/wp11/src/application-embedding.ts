/** Lifetime owner for one experimental application connection and durable caller slot.
 * No connection factory, file path or implicit replay is exposed to the renderer.
 * Stores/ports are trusted cooperative providers, not sandboxed code.
 */
import {ApplicationOwnerClient,applicationOwnerKey,validateApplicationContext,validateOriginalApplication} from './application-owner.js';
import type {ApplicationContext,ApplicationOwnerPort,CallerIntentStore,CallerRecord,OriginalApplication,ApplicationSnapshot,ApplicationOptions,ApplicationOwnerOperation} from './application-owner.js';
import {check,record,canonical,clone,freeze,count,list,ContractError} from './validate.js';
export type EmbeddingOperation='restore'|'stage'|'observe'|'prepare'|'dispatch'|'inquire'|'retire'|'abandon';
export interface EmbeddingState {
 readonly lifecycle:'DETACHED'|'ATTACHED'|'DETACHING'|'CLEANUP_UNCONFIRMED';
 readonly caller:'UNLOADED'|'EMPTY'|'SAVED'|'UNCERTAIN';
 readonly original:OriginalApplication|null;readonly dispatchAttempted:boolean;
 readonly snapshot:ApplicationSnapshot|null;readonly busy:boolean;readonly needsInquiry:boolean;
 readonly reason:string|null;readonly localExperiment:boolean;
 readonly pendingStore:number;readonly pendingRequests:number;
}
const errorCode=(e:unknown):string=>{
 const c=e&&typeof e==='object'?Object.getOwnPropertyDescriptor(e,'code')?.value:null;
 return typeof c==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/.test(c)?c:'APPLICATION_EMBEDDING_FAILED';
};
export class ApplicationEmbedding {
 readonly context:ApplicationContext;readonly targets:readonly string[];readonly localExperiment:boolean;
 private readonly key:string;private readonly trackedStore:CallerIntentStore;
 private client:ApplicationOwnerClient|null=null;
 private lifecycle:EmbeddingState['lifecycle']='DETACHED';private caller:EmbeddingState['caller']='UNLOADED';
 private original:OriginalApplication|null=null;private attempted=false;private inquiry=false;
 private why:string|null=null;private busy=false;private epoch=0;private invalidated=false;
 private cancelled=false;
 private storePending=0;private requestsPending=0;private actionPending=0;
 private closing:Promise<void>|null=null;private portClosed=false;private portCloseFailed=false;
 private viewOwned=false;private readonly listeners=new Set<()=>void>();
 constructor(context:ApplicationContext,private readonly store:CallerIntentStore,values:readonly string[],options:{localExperiment?:boolean}={}) {
  this.context=validateApplicationContext(context);this.key=applicationOwnerKey(this.context);
  check(store&&typeof store.load==='function'&&typeof store.save==='function'&&typeof store.markDispatch==='function','store','CALLER_STORE_REQUIRED');
  list(values,64,v=>check(typeof v==='string'&&/^[0-9a-f]{64}$/.test(v),'target'));
  check(values.length>0&&new Set(values).size===values.length,'targets');this.targets=freeze([...values].sort());
  const o=record(options,Object.keys(options));check(Object.keys(o).every(k=>k==='localExperiment'),'options');
  check(o.localExperiment===undefined||typeof o.localExperiment==='boolean','experiment');this.localExperiment=o.localExperiment===true;
  // Validate every provider read, including the second read inside client.restore.
  this.trackedStore={load:()=>this.trackStore(async()=>this.readRecord(await this.store.load())),save:v=>this.trackStore(()=>this.store.save(v)),markDispatch:id=>this.trackStore(()=>this.store.markDispatch(id))};
 }
 private async trackStore<T>(f:()=>Promise<T>):Promise<T>{this.storePending++;try{return await f();}finally{this.storePending--;}}
 private remember():void {
  const c=this.client?.current;if(!c)return;
  if(c.original!==null)this.original=c.original;
  this.attempted=this.attempted||c.dispatchAttempted;this.inquiry=this.inquiry||c.needsInquiry;
 }
 get current():EmbeddingState {
  this.remember();const c=this.client?.current;
  return freeze({lifecycle:this.lifecycle,caller:this.caller,original:this.original,dispatchAttempted:this.attempted,
   snapshot:this.lifecycle==='ATTACHED'&&!this.busy&&this.why===null&&c?.status==='CURRENT'?c.snapshot:null,
   busy:this.busy,needsInquiry:this.inquiry||!!c?.needsInquiry,reason:this.why??c?.reason??null,
   localExperiment:this.localExperiment,pendingStore:this.storePending,pendingRequests:this.requestsPending});
 }
 subscribe(fn:()=>void):()=>void {
  check(typeof fn==='function'&&this.listeners.size<8,'subscriber','APPLICATION_SUBSCRIBER_LIMIT');
  this.listeners.add(fn);return()=>{this.listeners.delete(fn);};
 }
 private notify():void {for(const fn of this.listeners){try{fn();}catch{/* Presentation callbacks cannot turn a completed operation into a failure. */}}}
 assertViewAvailable():void {check(!this.viewOwned,'one screen','APPLICATION_VIEW_OWNED');}
 acquireView():()=>void {
  check(!this.viewOwned,'one screen','APPLICATION_VIEW_OWNED');this.viewOwned=true;let active=true;
  return()=>{if(active){active=false;this.viewOwned=false;}};
 }
 /** Takes ownership only on success. Failed attachment leaves the supplied port with its caller. */
 attach(context:ApplicationContext,port:ApplicationOwnerPort):void {
  check(!this.invalidated,'invalidated','APPLICATION_CONTEXT_CHANGED');
  check(this.lifecycle==='DETACHED'&&this.actionPending===0&&this.storePending===0&&this.requestsPending===0,'owned','APPLICATION_CONNECTION_OWNED');
  const c=validateApplicationContext(context);check(applicationOwnerKey(c)===this.key,'stable owner','APPLICATION_CONTEXT_MISMATCH');
  check(port&&typeof port.request==='function'&&typeof port.close==='function','port');
  this.portClosed=false;this.portCloseFailed=false;this.closing=null;let closePromise:Promise<void>|null=null;
  const tracked:ApplicationOwnerPort={
   request:async(...args)=>{this.requestsPending++;try{return await port.request(...args);}finally{this.requestsPending--; }},
   close:()=>{
    if(closePromise===null){closePromise=Promise.resolve().then(()=>port.close()).then(()=>{this.portClosed=true;},e=>{this.portCloseFailed=true;throw e;});}
    return closePromise;
   }
  };
  this.client=new ApplicationOwnerClient(c,tracked,this.trackedStore);this.caller='UNLOADED';this.why=null;this.lifecycle='ATTACHED';this.epoch++;this.notify();
 }
 private idle():ApplicationOwnerClient {
  check(!this.invalidated,'invalidated','APPLICATION_CONTEXT_CHANGED');
  check(this.lifecycle==='ATTACHED'&&this.client!==null,'attach first','APPLICATION_ATTACH_REQUIRED');
  check(!this.busy,'busy','APPLICATION_EMBEDDING_BUSY');return this.client;
 }
 private async run<T>(f:(client:ApplicationOwnerClient,active:()=>void)=>Promise<T>):Promise<T> {
  const client=this.idle(),at=this.epoch;this.busy=true;this.actionPending++;this.why=null;this.cancelled=false;this.notify();
  const active=()=>{check(at===this.epoch&&this.lifecycle==='ATTACHED'&&!this.invalidated,'detached','APPLICATION_STALE_RESPONSE');check(!this.cancelled,'cancelled','CANCELLED');};
  try{active();const value=await f(client,active);active();this.remember();this.inquiry=client.current.needsInquiry;return value;}
  catch(e){this.remember();if(at===this.epoch)this.why=errorCode(e);throw e;}
  finally{this.actionPending--;this.busy=false;this.notify();}
 }
 private readRecord(raw:unknown):CallerRecord|null {
  if(raw===null){check(this.original===null&&!this.attempted,'known record missing','CALLER_INTENT_MISSING');return null;}
  const r=record(raw,['original','dispatchAttempted']);const original=validateOriginalApplication(r.original);
  check(original.ownerKey===this.key&&canonical(original.targets)===canonical(this.targets),'caller context','CALLER_CONTEXT_MISMATCH');
  check(typeof r.dispatchAttempted==='boolean','marker');
  if(this.original)check(canonical(original)===canonical(this.original),'original changed','CALLER_INTENT_CONFLICT');
  check(!this.attempted||r.dispatchAttempted,'known marker missing','CALLER_MARKER_MISSING');
  return freeze({original,dispatchAttempted:r.dispatchAttempted});
 }
 /** Read only; never creates a record, connection, intent or dispatch marker. */
 async restore():Promise<void>{
  return this.run(async(c,active)=>{try{
   const r=this.readRecord(await this.trackedStore.load());active();
   if(r===null){this.caller='EMPTY';return;}
   this.original=r.original;this.attempted=this.attempted||r.dispatchAttempted;this.inquiry=true;
   await c.restore();active();this.caller='SAVED';
  }catch(e){this.caller='UNCERTAIN';throw e;}});
 }
 /** Separate explicit local action. The UI never invents or replaces an ID. */
 async stage(operationId:string,expectedRevision:number):Promise<void>{
  this.idle();check(this.localExperiment,'explicit experiment','APPLICATION_EXPERIMENT_REQUIRED');
  count(expectedRevision,63);
  const original=validateOriginalApplication({profile:'par-caller-application-0052',ownerKey:this.key,operationId,expectedRevision,targets:this.targets});
  check(!this.attempted,'marker recorded','INQUIRY_REQUIRED');
  if(this.original)check(canonical(original)===canonical(this.original),'different ID','ORIGINAL_OPERATION_REQUIRED');
  return this.run(async(c,active)=>{try{
   const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(this.targets)));active();
   const sha=Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
   check(sha===this.context.document.targetDigest,'targets','APPLICATION_TARGETS');
   const prior=this.readRecord(await this.trackedStore.load());active();
   if(prior){check(canonical(prior.original)===canonical(original),'slot conflict','CALLER_INTENT_CONFLICT');check(!prior.dispatchAttempted,'marker','INQUIRY_REQUIRED');}
   this.original=original;this.inquiry=true;this.caller='UNCERTAIN';
   await this.trackedStore.save(original);active();
   const stored=this.readRecord(await this.trackedStore.load());active();check(stored!==null&&!stored.dispatchAttempted,'save readback','CALLER_STORE_UNCERTAIN');
   await c.restore();active();this.caller='SAVED';
  }catch(e){this.caller='UNCERTAIN';throw e;}});
 }
 can(op:EmbeddingOperation):boolean {
  const s=this.current;if(s.lifecycle!=='ATTACHED'||s.busy||this.invalidated)return false;
  if(op==='restore'||op==='observe')return true;
  if(op==='stage')return this.localExperiment&&!s.dispatchAttempted&&s.original===null;
  if(s.caller!=='SAVED'||s.original===null||!s.snapshot)return false;
  if(!s.snapshot.operations.includes(op as ApplicationOwnerOperation))return false;
  if(op==='inquire')return true;
  if(!this.localExperiment||s.snapshot.capability!=='LOCAL_EXPERIMENT')return false;
  if(op==='prepare')return !s.dispatchAttempted&&['EMPTY','PREPARED'].includes(s.snapshot.journal.state);
  if(op==='dispatch')return !s.dispatchAttempted&&!s.needsInquiry&&s.snapshot.journal.state==='PREPARED';
  if(op==='retire')return s.snapshot.journal.state==='OBSERVED';
  return !s.dispatchAttempted&&s.snapshot.journal.state==='PREPARED';
 }
 observe(options:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.run(c=>c.observe(options));}
 prepare(options:ApplicationOptions={}):Promise<ApplicationSnapshot>{
  return this.run((c)=>{check(this.localExperiment,'experiment','APPLICATION_EXPERIMENT_REQUIRED');check(this.caller==='SAVED'&&this.original!==null,'stage first','CALLER_INTENT_REQUIRED');const i=this.original;return c.prepare(i.operationId,i.expectedRevision,i.targets,options);});
 }
 private action(op:'dispatch'|'inquire'|'retire'|'abandon',options:ApplicationOptions):Promise<ApplicationSnapshot>{
  return this.run(c=>{if(op!=='inquire')check(this.localExperiment,'experiment','APPLICATION_EXPERIMENT_REQUIRED');check(this.caller==='SAVED','restore first','CALLER_INTENT_REQUIRED');return c[op](options);});
 }
 dispatch(o:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('dispatch',o);}
 inquire(o:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('inquire',o);}
 retire(o:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('retire',o);}
 abandon(o:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('abandon',o);}
 cancel():void {if(this.busy)this.cancelled=true;this.client?.cancel();}
 /** Authority changes require a separately reviewed binding; no automatic migration. */
 invalidate():Promise<void>{this.invalidated=true;this.why='APPLICATION_CONTEXT_CHANGED';return this.detach();}
 /** The retained close promise is not retried after a failure. No persistent record is removed. */
 detach():Promise<void>{
  if(this.closing!==null)return this.closing;
  if(this.lifecycle==='DETACHED')return Promise.resolve();
  this.remember();this.lifecycle='DETACHING';this.epoch++;this.client?.cancel();this.notify();
  const c=this.client;
  this.closing=(async()=>{
   try{await c?.close();this.remember();if(!this.checkCleanup())throw new ContractError('CLEANUP_UNCONFIRMED');}
   catch(e){this.lifecycle='CLEANUP_UNCONFIRMED';this.why='CLEANUP_UNCONFIRMED';this.notify();throw e;}
  })();
  return this.closing;
 }
 /** Explicitly poll a late cooperative completion; never repeats close or cancels finalizers. */
 checkCleanup():boolean {
  if(this.lifecycle==='DETACHED')return true;
  if(this.lifecycle==='ATTACHED'||!this.portClosed||this.portCloseFailed||this.storePending||this.requestsPending||this.actionPending)return false;
  this.remember();this.client=null;this.lifecycle='DETACHED';if(this.why==='CLEANUP_UNCONFIRMED')this.why=null;this.notify();return true;
 }
}
