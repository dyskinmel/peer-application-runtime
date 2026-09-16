import {copyData} from './owner-data.js';
/** Explicit experimental apply client. No default persistence, replay or reconnect.
 * A CallerIntentStore is a trusted durability port, not an authorization token.
 */
import {check,record,count,list,enumValue,string,clone,freeze,canonical,ContractError} from './validate.js';
import {validateFetchPin,validateFetchObservation} from './fetch-observation.js';
import type {FetchPin,FetchObservation} from './fetch-observation.js';
export const APPLICATION_OWNER_PROTOCOL='par-owner-application-0052';
export const APPLICATION_OWNER_OPERATIONS=['abandon','close','dispatch','inquire','observe','prepare','retire'] as const;
export type ApplicationOwnerOperation=typeof APPLICATION_OWNER_OPERATIONS[number];
export interface ApplicationContext {readonly profile:typeof APPLICATION_OWNER_PROTOCOL;readonly document:FetchPin;readonly journalId:string;readonly bindingDigest:string;}
export interface OriginalApplication {readonly profile:'par-caller-application-0052';readonly ownerKey:string;readonly operationId:string;readonly expectedRevision:number;readonly targets:readonly string[];}
export interface CallerRecord {readonly original:OriginalApplication;readonly dispatchAttempted:boolean;}
export interface CallerIntentStore {
 load():Promise<CallerRecord|null>;
 /** Durable create-only or identical readback. Failure can mean stored-but-unacknowledged. */
 save(original:OriginalApplication):Promise<void>;
 /** Durable exclusive marker. Repeating it MUST fail, even for the same ID. */
 markDispatch(operationId:string):Promise<void>;
}
export interface ApplicationOwnerPort {request(op:ApplicationOwnerOperation,args:unknown,signal:AbortSignal):Promise<unknown>;close():Promise<void>;}
export interface ApplicationOptions {signal?:AbortSignal;timeoutMs?:number;}
export interface ApplicationIntentView {readonly operationId:string;readonly expectedRevision:number;readonly targets:readonly string[];readonly digest:string;}
export interface ApplicationReceipt {readonly profile:string;readonly operationId:string;readonly revision:number;readonly heads:readonly string[];readonly inputIds:readonly string[];readonly eventDigest:string;readonly candidatePersisted:true;readonly innerValidated:boolean;readonly applied:boolean;readonly replicated:false;readonly phase:string;readonly productQualified:false;}
export interface ApplicationJournalView {
 readonly state:'EMPTY'|'PREPARED'|'DISPATCHED'|'OBSERVED'|'RETIRED'|'ABANDONED';
 readonly intentDigest:string|null;readonly operationId:string|null;readonly receipt:ApplicationReceipt|null;
 readonly sequence:number;readonly replayAllowed:false;readonly applied:false;readonly replicated:false;
 readonly acknowledged:false;readonly productQualified:false;readonly operationState:string;readonly reason:string|null;readonly needsInquiry:boolean;
}
export interface ApplicationSnapshot {readonly profile:typeof APPLICATION_OWNER_PROTOCOL;readonly context:ApplicationContext;readonly observation:FetchObservation;readonly journal:ApplicationJournalView;readonly intent:ApplicationIntentView|null;readonly operations:readonly ApplicationOwnerOperation[];readonly capability:'LOCAL_EXPERIMENT'|'READ_ONLY_UNQUALIFIED';}
export interface ApplicationClientState {readonly status:'NOT_OBSERVED'|'BUSY'|'CURRENT'|'UNAVAILABLE'|'CLOSED';readonly snapshot:ApplicationSnapshot|null;readonly original:OriginalApplication|null;readonly dispatchAttempted:boolean;readonly needsInquiry:boolean;readonly reason:string|null;}
const hex=(v:unknown,n=64):void=>check(typeof v==='string'&&new RegExp(`^[0-9a-f]{${n}}$`).test(v),'hex');
const reason=(e:unknown):string=>{const c=e&&typeof e==='object'?Object.getOwnPropertyDescriptor(e,'code')?.value:undefined;return typeof c==='string'&&/^[A-Z][A-Z0-9_]{0,63}$/.test(c)?c:'APPLICATION_REQUEST_FAILED';};
const validCode=(v:unknown):void=>check(v===null||typeof v==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/.test(v),'reason');
async function hash(v:unknown):Promise<string>{const r=await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v)));return [...new Uint8Array(r)].map(b=>b.toString(16).padStart(2,'0')).join('');}
function targets(value:unknown):readonly string[]{list(value,64,v=>hex(v));check(value.length>0&&new Set(value).size===value.length,'targets');return freeze((value as string[]).slice().sort());}
export function validateApplicationContext(value:unknown):ApplicationContext {
 const v=record(value,['profile','document','journalId','bindingDigest']);check(v.profile===APPLICATION_OWNER_PROTOCOL,'profile');hex(v.journalId);hex(v.bindingDigest);
 return freeze({profile:APPLICATION_OWNER_PROTOCOL,document:validateFetchPin(v.document),journalId:v.journalId as string,bindingDigest:v.bindingDigest as string});
}
export function applicationOwnerKey(context:ApplicationContext):string {
 const c=validateApplicationContext(context);const {streamId:_,...document}=c.document;
 return canonical({...c,document}); // Stable across process restart, NOT across scope/authority/generation changes.
}
export function validateOriginalApplication(value:unknown):OriginalApplication {
 const v=record(value,['profile','ownerKey','operationId','expectedRevision','targets']);check(v.profile==='par-caller-application-0052','caller profile');string(v.ownerKey,4096);hex(v.operationId,32);count(v.expectedRevision,63);
 const ids=targets(v.targets);check(canonical(v.targets)===canonical(ids),'canonical targets');
 return freeze(clone(v)) as unknown as OriginalApplication;
}
function callerRecord(value:unknown,key:string):CallerRecord|null {
 if(value===null)return null;const v=record(value,['original','dispatchAttempted']);const original=validateOriginalApplication(v.original);check(original.ownerKey===key,'stored owner','CALLER_CONTEXT_MISMATCH');check(typeof v.dispatchAttempted==='boolean','marker');return freeze({original,dispatchAttempted:v.dispatchAttempted});
}
function receipt(value:unknown,intent:ApplicationIntentView):ApplicationReceipt {
 const r=record(value,['profile','operationId','revision','heads','inputIds','eventDigest','candidatePersisted','innerValidated','applied','replicated','phase','productQualified']);
 check(r.profile==='par-document-apply-local-0035'&&r.operationId===intent.operationId&&r.revision===intent.expectedRevision+1,'receipt binding');hex(r.eventDigest);
 for(const key of ['heads','inputIds']){list(r[key],128,x=>hex(x));const a=r[key] as string[];check(a.length>0&&new Set(a).size===a.length,'receipt IDs');}
 check(intent.targets.every(t=>(r.inputIds as string[]).includes(t)),'receipt targets');
 check(r.candidatePersisted===true&&r.replicated===false&&r.productQualified===false,'receipt claims');check(typeof r.applied==='boolean'&&r.innerValidated===r.applied,'validated');
 check(r.phase===(r.applied?'CORE_VALIDATED_LOCAL_APPLY':'CANDIDATE_ONLY'),'phase');return freeze(clone(r)) as unknown as ApplicationReceipt;
}
async function snapshot(value:unknown,context:ApplicationContext):Promise<ApplicationSnapshot>{
 const v=record(copyData(value),['profile','context','observation','journal','intent','operations','capability']);check(v.profile===APPLICATION_OWNER_PROTOCOL,'snapshot profile');check(canonical(validateApplicationContext(v.context))===canonical(context),'context','APPLICATION_CONTEXT_MISMATCH');
 list(v.operations,APPLICATION_OWNER_OPERATIONS.length,o=>enumValue(o,APPLICATION_OWNER_OPERATIONS));check(new Set(v.operations).size===v.operations.length&&v.operations.includes('observe'),'operations');enumValue(v.capability,['LOCAL_EXPERIMENT','READ_ONLY_UNQUALIFIED']);
 if(v.capability!=='LOCAL_EXPERIMENT')check(v.operations.every(o=>['observe','inquire','close'].includes(o as string)),'unqualified grant');
 let i:ApplicationIntentView|null=null;
 if(v.intent!==null){const t=record(v.intent,['operationId','expectedRevision','targets','digest']);hex(t.operationId,32);count(t.expectedRevision,63);hex(t.digest);const ids=targets(t.targets);check(await hash(ids)===context.document.targetDigest,'intent targets');i=freeze({...t,targets:ids}) as unknown as ApplicationIntentView;}
 const j=record(v.journal,['state','intentDigest','operationId','receipt','sequence','replayAllowed','applied','replicated','acknowledged','productQualified','operationState','reason','needsInquiry']);
 enumValue(j.state,['EMPTY','PREPARED','DISPATCHED','OBSERVED','RETIRED','ABANDONED']);count(j.sequence,256);validCode(j.reason);
 for(const k of ['replayAllowed','applied','replicated','acknowledged','productQualified'])check(j[k]===false,'non-claim');
 enumValue(j.operationState,['EMPTY','PREPARED','DISPATCHED','OBSERVED','RETIRED','ABANDONED','OBSERVED_APPLICATION_RECORD','NOT_OBSERVED','OUTCOME_UNKNOWN','CORE_BLOCKED','CANCELLED','REJECTED','INQUIRY_FAILED']);
 check(j.needsInquiry===['DISPATCHED','OBSERVED'].includes(j.state as string),'inquiry state');check((i===null)===(j.state==='EMPTY'),'empty intent');
 check(j.operationId===(i?.operationId??null)&&j.intentDigest===(i?.digest??null),'journal binding');
 check((j.receipt!==null)===['OBSERVED','RETIRED'].includes(j.state as string),'receipt state');if(j.receipt!==null){check(i!==null,'receipt intent');receipt(j.receipt,i);}
 const obs=await validateFetchObservation(v.observation,context.document);
 return freeze(clone({...v,context,observation:obs,intent:i})) as unknown as ApplicationSnapshot;
}
function options(value:ApplicationOptions):{signal:AbortSignal|undefined;timeoutMs:number}{
 check(value!==null&&typeof value==='object','options');const keys=Object.keys(value);check(keys.every(k=>['signal','timeoutMs'].includes(k)),'option keys');const v=record(value,keys);check(v.signal===undefined||v.signal instanceof AbortSignal,'signal');const ms=v.timeoutMs??10000;count(ms,60000);check(ms>=50,'timeout');return{signal:v.signal as AbortSignal|undefined,timeoutMs:ms};
}
export class ApplicationOwnerClient {
 readonly context:ApplicationContext;private readonly key:string;private busy=false;private closed=false;private epoch=0;
 private aborter:AbortController|null=null;private original:OriginalApplication|null=null;private attempted=false;private needsInquiry=false;
 private sequence=0n;private journalSequence=0;private knownReceipt:ApplicationReceipt|null=null;
 private state:ApplicationClientState=freeze({status:'NOT_OBSERVED',snapshot:null,original:null,dispatchAttempted:false,needsInquiry:false,reason:null});
 constructor(context:ApplicationContext,private readonly port:ApplicationOwnerPort,private readonly store:CallerIntentStore){
  this.context=validateApplicationContext(context);this.key=applicationOwnerKey(this.context);
  check(port&&typeof port.request==='function'&&typeof port.close==='function','port');
  check(store&&typeof store.load==='function'&&typeof store.save==='function'&&typeof store.markDispatch==='function','durable store required','CALLER_STORE_REQUIRED');
 }
 get current():ApplicationClientState{return this.state;}
 private set(status:ApplicationClientState['status'],value:ApplicationSnapshot|null=null,error:string|null=null):void {this.state=freeze({status,snapshot:value,reason:error,original:this.original,dispatchAttempted:this.attempted,needsInquiry:this.needsInquiry});}
 private idle():void{check(!this.closed,'closed','APPLICATION_CLIENT_CLOSED');check(!this.busy,'busy','APPLICATION_CLIENT_BUSY');}
 private currentFor(op:ApplicationOwnerOperation):ApplicationSnapshot{this.idle();const s=this.state.snapshot;check(this.state.status==='CURRENT'&&s!==null,'observe first','APPLICATION_OBSERVE_REQUIRED');check(s.operations.includes(op),'grant','OWNER_OPERATION_DENIED');return s;}
 async restore():Promise<void>{
  this.idle();this.busy=true;const epoch=++this.epoch;this.set('BUSY');
  try{const r=callerRecord(await this.store.load(),this.key);check(!this.closed&&epoch===this.epoch,'closed','APPLICATION_STALE_RESPONSE');
   check(r!==null,'original missing','CALLER_INTENT_MISSING');this.original=r.original;this.attempted=r.dispatchAttempted;this.needsInquiry=true;this.set('UNAVAILABLE',null,'RECONCILE_REQUIRED');
  }catch(e){if(!this.closed&&epoch===this.epoch)this.set('UNAVAILABLE',null,reason(e));throw e;}finally{if(epoch===this.epoch)this.busy=false;}
 }
 private async invoke(op:ApplicationOwnerOperation,args:Record<string,unknown>,opts:ApplicationOptions={},before?:(active:()=>void)=>Promise<void>):Promise<ApplicationSnapshot>{
  this.idle();const o=options(opts);check(!o.signal?.aborted,'cancelled','CANCELLED');
  this.busy=true;const epoch=++this.epoch,aborter=new AbortController();this.aborter=aborter;let why='CANCELLED';
  const active=()=>{check(!this.closed&&epoch===this.epoch,'late','APPLICATION_STALE_RESPONSE');check(!aborter.signal.aborted,'cancelled',why);};
  let rejectAbort:()=>void=()=>{};const cancelled=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new ContractError(why));aborter.signal.addEventListener('abort',rejectAbort,{once:true});});
  const forward=()=>aborter.abort();o.signal?.addEventListener('abort',forward,{once:true});const timer=setTimeout(()=>{why='APPLICATION_TIMEOUT';aborter.abort();},o.timeoutMs);this.set('BUSY');
  try{
   const run=async()=>{active();if(before)await before(active);active();const raw=await this.port.request(op,{context:clone(this.context),...args,timeoutMs:o.timeoutMs},aborter.signal);active();const s=await snapshot(raw,this.context);active();
    check(BigInt(s.observation.sequence)>this.sequence&&s.journal.sequence>=this.journalSequence,'old result','APPLICATION_STALE_RESPONSE');
    if(this.original&&s.intent){check(s.intent.operationId===this.original.operationId&&s.intent.expectedRevision===this.original.expectedRevision&&canonical(s.intent.targets)===canonical(this.original.targets),'original intent','ORIGINAL_OPERATION_REQUIRED');}
    if(this.knownReceipt)check(canonical(s.journal.receipt)===canonical(this.knownReceipt),'receipt conflict','RECEIPT_CONFLICT');
    this.sequence=BigInt(s.observation.sequence);this.journalSequence=s.journal.sequence;this.knownReceipt=s.journal.receipt;
    this.needsInquiry=s.journal.needsInquiry||(this.attempted&&s.journal.state!=='RETIRED');
    if(op==='prepare')this.needsInquiry=false;
    this.set('CURRENT',s);return s;};
   return await Promise.race([run(),cancelled]);
  }catch(e){if(op!=='observe')this.needsInquiry=true;if(!this.closed&&epoch===this.epoch)this.set('UNAVAILABLE',null,reason(e));throw e;
  }finally{clearTimeout(timer);o.signal?.removeEventListener('abort',forward);aborter.signal.removeEventListener('abort',rejectAbort);if(epoch===this.epoch){this.busy=false;this.aborter=null;}}
 }
 async observe(opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.invoke('observe',{},opts);}
 async prepare(operationId:string,expectedRevision:number,values:readonly string[],opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{
  this.idle();hex(operationId,32);count(expectedRevision,63);const ids=targets(values);const o=options(opts);check(!o.signal?.aborted,'cancelled','CANCELLED');
  check(await hash(ids)===this.context.document.targetDigest,'targets','APPLICATION_TARGETS');
  const s=this.currentFor('prepare');check(!this.attempted,'dispatch already recorded','INQUIRY_REQUIRED');
  const original:OriginalApplication=freeze({profile:'par-caller-application-0052',ownerKey:this.key,operationId,expectedRevision,targets:ids});
  if(this.original)check(canonical(original)===canonical(this.original),'new ID prohibited','ORIGINAL_OPERATION_REQUIRED');
  return this.invoke('prepare',{expectedRevision:s.observation.revision,operationId,expectedApplyRevision:expectedRevision,targetDigest:this.context.document.targetDigest},opts,async active=>{
   this.original=original;this.needsInquiry=true;const prior=callerRecord(await this.store.load(),this.key);active();
   if(prior){check(canonical(prior.original)===canonical(original),'store conflict','CALLER_INTENT_CONFLICT');this.attempted=prior.dispatchAttempted;check(!this.attempted,'dispatch','INQUIRY_REQUIRED');}
   await this.store.save(original);active();
   const stored=callerRecord(await this.store.load(),this.key);active();check(stored!==null&&!stored.dispatchAttempted&&canonical(stored.original)===canonical(original),'durable readback','CALLER_STORE_UNCERTAIN');
  });
 }
 private action(op:'dispatch'|'inquire'|'retire'|'abandon',opts:ApplicationOptions):Promise<ApplicationSnapshot>{
  const s=this.currentFor(op);check(this.original!==null,'restore original','CALLER_INTENT_REQUIRED');const i=this.original;
  if(op==='dispatch'){check(!this.attempted&&!this.needsInquiry&&s.journal.state==='PREPARED','inquire only','INQUIRY_REQUIRED');}
  const args={expectedRevision:s.observation.revision,operationId:i.operationId,expectedApplyRevision:i.expectedRevision,intentDigest:s.intent?.digest??null};
  return this.invoke(op,args,opts,op==='dispatch'?async active=>{this.attempted=true;this.needsInquiry=true;await this.store.markDispatch(i.operationId);active();
   const stored=callerRecord(await this.store.load(),this.key);active();check(stored!==null&&stored.dispatchAttempted&&canonical(stored.original)===canonical(i),'dispatch marker readback','CALLER_STORE_UNCERTAIN');
  }:undefined);
 }
 async dispatch(opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('dispatch',opts);}
 async inquire(opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('inquire',opts);}
 async retire(opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('retire',opts);}
 async abandon(opts:ApplicationOptions={}):Promise<ApplicationSnapshot>{return this.action('abandon',opts);}
 cancel():void{this.aborter?.abort();}
 async close():Promise<void>{
  if(this.closed)return;this.closed=true;this.epoch++;this.aborter?.abort();this.busy=false;this.set('CLOSED');
  // Keep the promise referenced by this invocation and surface an unconfirmed close.
  let timer:ReturnType<typeof setTimeout>|undefined;
  try{await Promise.race([this.port.close(),new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new ContractError('CLEANUP_UNCONFIRMED')),2000);})]);}
  catch(e){this.set('CLOSED',null,'CLEANUP_UNCONFIRMED');throw e;}finally{if(timer!==undefined)clearTimeout(timer);}
 }
}
export function presentApplicationOwner(state:ApplicationClientState,locale:'ja'|'en'):string {
 enumValue(locale,['ja','en']);const ja=locale==='ja';
 if(state.status==='CLOSED')return ja?'接続を終了しました。記録は削除しません。':'Connection closed. Records retained.';
 if(state.status==='BUSY')return ja?'処理中。取消しは保存の取消しではありません。':'Processing. Cancellation is not rollback.';
 if(state.status==='UNAVAILABLE')return ja?'結果を確認できません。元の操作IDで照会してください。':'Result unavailable. Inquire using the original operation ID.';
 const j=state.snapshot?.journal;if(!j)return ja?'未確認':'Not observed';
 if(j.operationState==='INQUIRY_FAILED')return ja?'照会失敗。再実行は許可されていません。':'Inquiry failed. Replay is not permitted.';
 if(j.operationState==='CORE_BLOCKED')return ja?'実コアを利用できないため停止しています。':'Blocked: real core unavailable.';
 const labels={EMPTY:['意図未作成','No prepared intent'],PREPARED:['準備済み・未適用','Prepared, not applied'],DISPATCHED:['適用結果不明・元ID照会のみ','Outcome unknown; original-ID inquiry only'],OBSERVED:['適用記録を確認済み・複製証明ではありません','Application record observed; not replication evidence'],RETIRED:['終了記録を保存済み','Retirement record stored'],ABANDONED:['実行前に明示終了','Explicitly abandoned before dispatch']} as const;
 return labels[j.state][ja?0:1];
}
