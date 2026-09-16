/** Owner-injected fetch observation. This is a separate candidate panel, never
 * NoteState, a shared commit receipt, CRDT proof, or an automatic retry trigger. */
import {canonical,check,clone,count,enumValue,freeze,list,record,string,u64,ContractError} from './validate.js';
const PROFILE='par-fetch-observation-local-0046' as const;
const ROOT_STATES=['NOT_OBSERVED','WAITING_DEPENDENCIES','READY_FOR_CORE','QUARANTINED','WAITING_AUTHORITY','REBASE_REQUIRED','INVALID_DEPENDENCY_GRAPH','RESOURCE_BLOCKED'] as const;
const VALIDATION_STATES=[...ROOT_STATES,'CORE_BLOCKED','CORE_REJECTED','SEMANTICALLY_VALIDATED_PENDING','CONTRACT_CHECKED'] as const;
const OP_STATES=['NOT_REQUESTED','REQUESTED','CORE_BLOCKED','REJECTED','OUTCOME_UNKNOWN','INQUIRY_FAILED','NOT_OBSERVED','OBSERVED_APPLICATION_RECORD'] as const;
export interface FetchPin {
 readonly profile:typeof PROFILE;
 readonly scope:Readonly<{appId:string;spaceId:string;documentId:string;epoch:string;schemaId:string;controlHead:string}>;
 readonly planDigest:string;readonly targetDigest:string;readonly inboxGeneration:string;
 readonly storeGeneration:string;readonly connectionGeneration:string;readonly streamId:string;
}
export interface FetchObservation {
 readonly profile:typeof PROFILE;readonly pin:FetchPin;readonly sequence:string;readonly revision:string;readonly localRevision:string;
 readonly records:readonly Readonly<{envelopeId:string;state:typeof ROOT_STATES[number];inboxStored:boolean;
   missingInner:readonly string[];missingPrevious:readonly string[];
   validation:Readonly<{state:typeof VALIDATION_STATES[number];reason:string|null}>|null}>[];
 readonly operation:Readonly<{id:string|null;state:typeof OP_STATES[number];reason:string|null;revision:number|null;expectedRevision:number|null}>;
 readonly innerValidated:false;readonly applied:false;readonly localCommitted:false;readonly replicated:false;
 readonly acknowledged:false;readonly productQualified:false;
}
function hex(v:unknown,size=64):asserts v is string{check(typeof v==='string'&&v.length===size&&/^[0-9a-f]+$/.test(v),'hex identifier');}
function reason(v:unknown):void{check(v===null||(typeof v==='string'&&/^[A-Z_]{1,80}$/.test(v)),'reason code');}
function pinValue(value:unknown):FetchPin{
 const p=record(value,['profile','scope','planDigest','targetDigest','inboxGeneration','storeGeneration','connectionGeneration','streamId']);
 check(p.profile===PROFILE,'profile');const s=record(p.scope,['appId','spaceId','documentId','epoch','schemaId','controlHead']);string(s.appId,512);
 for(const k of ['spaceId','documentId','schemaId','controlHead'])hex(s[k]);u64(s.epoch);check(BigInt(s.epoch)>0n,'epoch');
 hex(p.planDigest);hex(p.targetDigest);for(const k of ['inboxGeneration','storeGeneration','streamId'])hex(p[k],32);
 u64(p.connectionGeneration);check(BigInt(p.connectionGeneration)<2n**63n,'connection generation');
 return freeze(clone(p as unknown as FetchPin));
}
function ids(v:unknown):void{list(v,128,x=>hex(x));check(new Set(v).size===v.length,'duplicate identifiers');for(let i=1;i<v.length;i++)check((v[i-1] as string)<(v[i] as string),'identifier order');}
async function hash(value:unknown):Promise<string>{const data=new TextEncoder().encode(canonical(value));const result=await globalThis.crypto.subtle.digest('SHA-256',data);return Array.from(new Uint8Array(result),b=>b.toString(16).padStart(2,'0')).join('');}
/** Structural validation precedes cloning/hashing, so getters and array hooks
 * cannot execute. SHA binds bytes; trust still comes from the owner/port. */
export async function validateFetchObservation(value:unknown,expectedPin:FetchPin):Promise<FetchObservation>{
 const expected=pinValue(expectedPin);
 const v=record(value,['profile','pin','sequence','revision','localRevision','records','operation','innerValidated','applied','localCommitted','replicated','acknowledged','productQualified']);
 check(v.profile===PROFILE,'profile');const pin=pinValue(v.pin);check(canonical(pin)===canonical(expected),'pinned context','FETCH_PIN_MISMATCH');
 u64(v.sequence);check(BigInt(v.sequence)>0n,'sequence');hex(v.revision);hex(v.localRevision);
 for(const k of ['innerValidated','applied','localCommitted','replicated','acknowledged','productQualified'])check(v[k]===false,'non-claim '+k);
 list(v.records,64,item=>{
  const row=record(item,['envelopeId','state','inboxStored','missingInner','missingPrevious','validation']);hex(row.envelopeId);enumValue(row.state,ROOT_STATES);
  check(typeof row.inboxStored==='boolean','inbox stored');check(row.inboxStored===(row.state!=='NOT_OBSERVED'),'stored state');ids(row.missingInner);ids(row.missingPrevious);
  if(row.state!=='WAITING_DEPENDENCIES')check((row.missingInner as unknown[]).length===0&&(row.missingPrevious as unknown[]).length===0,'unexpected missing ids');
  if(row.validation!==null){const x=record(row.validation,['state','reason']);enumValue(x.state,VALIDATION_STATES);reason(x.reason);check(x.state!=='CONTRACT_CHECKED','synthetic result is not accepted by this binding');}
 });
 check(v.records.length>0,'targets empty');const roots=(v.records as unknown as FetchObservation['records']).map(r=>r.envelopeId);check(new Set(roots).size===roots.length,'duplicate roots');for(let i=1;i<roots.length;i++)check(roots[i-1]!<roots[i]!,'root order');
 const op=record(v.operation,['id','state','reason','revision','expectedRevision']);enumValue(op.state,OP_STATES);reason(op.reason);
 if(op.id===null)check(op.state==='NOT_REQUESTED'&&op.revision===null&&op.expectedRevision===null&&op.reason===null,'empty operation');
 else{hex(op.id,32);check(op.state!=='NOT_REQUESTED','operation state');count(op.expectedRevision,63);if(op.state==='OBSERVED_APPLICATION_RECORD'){count(op.revision,64);check(op.revision>0,'observed revision');}else check(op.revision===null,'unobserved revision');}
 const owned=clone(v as unknown as FetchObservation);check(new TextEncoder().encode(canonical(owned)).byteLength<=262144,'observation size');
 const {revision,...without}=owned;check(await hash(without)===revision,'observation digest','FETCH_DIGEST_MISMATCH');check(await hash(roots)===pin.targetDigest,'target digest','FETCH_TARGET_MISMATCH');
 return freeze(owned);
}
export interface FetchStatusPanel {
 readonly profile:'par-fetch-status-panel-0046';readonly targets:number;readonly missing:number;
 readonly message:string;readonly disclaimer:string;readonly applied:false;readonly acknowledged:false;
 readonly automaticRetry:false;readonly sharedCommit:false;readonly remoteProtection:false;
}
export function presentFetchObservation(v:FetchObservation,locale:'ja'|'en'):FetchStatusPanel{
 check(locale==='ja'||locale==='en','locale');
 const missing=new Set(v.records.flatMap(r=>[...r.missingInner,...r.missingPrevious])).size;
 const blocked=v.records.some(r=>r.validation?.state==='CORE_BLOCKED')||v.operation.state==='CORE_BLOCKED';
 const review=v.records.some(r=>['QUARANTINED','INVALID_DEPENDENCY_GRAPH','REBASE_REQUIRED','WAITING_AUTHORITY','RESOURCE_BLOCKED'].includes(r.state));
 const unknown=['OUTCOME_UNKNOWN','INQUIRY_FAILED','NOT_OBSERVED'].includes(v.operation.state);
 const recorded=v.operation.state==='OBSERVED_APPLICATION_RECORD';
 const message=locale==='ja'?
  unknown?'適用結果は未確定です。元の操作IDで明示的に照会してください。':recorded?'適用処理の記録を観測しました。共有文書の現在の状態は別に確認してください。':review?'候補の確認が必要です。自動で取得・適用しません。':blocked?'実コアによる検証は停止中です。候補は文書へ未適用です。':missing?`不足依存 ${missing} 件。次の取得計画を明示的に確認してください。`:'依存候補を確認しました。文書への適用は別の明示操作です。':
  unknown?'Application outcome is unconfirmed. Explicitly inquire with the original operation ID.':recorded?'An application record was observed. Check the current shared document state separately.':review?'Candidate review is required. No automatic fetch or apply.':blocked?'Core validation is blocked. Candidates are not applied to the document.':missing?`${missing} missing dependencies. Explicitly review the next fetch plan.`:'Dependency candidates observed. Document application is a separate explicit action.';
 return freeze({profile:'par-fetch-status-panel-0046',targets:v.records.length,missing,message,
  disclaimer:locale==='ja'?'候補の保存・検証結果であり、共有文書の保存や他端末の保管を証明しません。':'Candidate observations are not shared commits or remote retention proofs.',
  applied:false,acknowledged:false,automaticRetry:false,sharedCommit:false,remoteProtection:false});
}
export interface FetchObservationPort {observe():Promise<unknown>;}
export interface FetchBindingState {readonly status:'NOT_OBSERVED'|'CHECKING'|'CURRENT'|'UNAVAILABLE'|'CLOSED';readonly observation:FetchObservation|null;}
export class FetchReadBinding {
 private readonly pin:FetchPin;private ticket=0;private sequence=0n;private closed=false;
 private state:FetchBindingState=freeze({status:'NOT_OBSERVED',observation:null});
 private readonly knownOperations=new Map<string,number>();
 constructor(pin:FetchPin,private readonly port:FetchObservationPort){this.pin=pinValue(pin);check(port!==null&&typeof port==='object'&&typeof port.observe==='function','owner port');}
 get current():FetchBindingState{return this.state;}
 close():void{this.closed=true;this.ticket++;this.state=freeze({status:'CLOSED',observation:null});}
 async refresh():Promise<FetchBindingState>{
  check(!this.closed,'closed','FETCH_BINDING_CLOSED');const ticket=++this.ticket;
  this.state=freeze({status:'CHECKING',observation:null});
  const current=()=>check(!this.closed&&ticket===this.ticket,'late response','STALE_FETCH_RESPONSE');
  try{
   const raw=await this.port.observe();current();const value=await validateFetchObservation(raw,this.pin);current();
   check(BigInt(value.sequence)>this.sequence,'old sequence','STALE_FETCH_OBSERVATION');
   const op=value.operation;
   if(op.id!==null){const known=this.knownOperations.get(op.id);if(known!==undefined)check(op.state==='OBSERVED_APPLICATION_RECORD'&&op.revision===known,'known operation changed','FETCH_OPERATION_CONFLICT');
    if(op.state==='OBSERVED_APPLICATION_RECORD'){check(this.knownOperations.has(op.id)||this.knownOperations.size<64,'operation observation budget');this.knownOperations.set(op.id,op.revision!);}}
   this.sequence=BigInt(value.sequence);this.state=freeze({status:'CURRENT',observation:value});return this.state;
  }catch(error){if(!this.closed&&ticket===this.ticket)this.state=freeze({status:'UNAVAILABLE',observation:null});throw error;}
 }
}
export interface FetchStatusRenderer {refresh():Promise<void>;setLocale(locale:'ja'|'en'):void;destroy():void;}
/** Borrowed binding; destroying this view never closes another owner's port. */
export function mountFetchStatus(root:HTMLElement,binding:FetchReadBinding,initialLocale:'ja'|'en'='ja'):FetchStatusRenderer{
 let alive=true,locale=initialLocale;check(locale==='ja'||locale==='en','locale');
 const doc=root.ownerDocument,panel=doc.createElement('section'),message=doc.createElement('p'),disclaimer=doc.createElement('p');
 panel.setAttribute('role','status');panel.setAttribute('aria-live','polite');panel.append(message,disclaimer);root.replaceChildren(panel);
 function render(){if(!alive)return;const value=binding.current;
  if(value.observation!==null){const model=presentFetchObservation(value.observation,locale);message.textContent=model.message;disclaimer.textContent=model.disclaimer;}
  else{message.textContent=locale==='ja'?(value.status==='CHECKING'?'候補の状態を確認中です。':'現在の候補状態は未確認です。'):(value.status==='CHECKING'?'Checking candidate state.':'Current candidate state is unconfirmed.');disclaimer.textContent='';}}
 render();return{async refresh(){const pending=binding.refresh();render();try{await pending;}finally{render();}},
  setLocale(next){check(next==='ja'||next==='en','locale');locale=next;render();},
  destroy(){alive=false;root.replaceChildren();}};
}
/** Same validator used by the private fetch command transport handshake. */
export {pinValue as validateFetchPin};
