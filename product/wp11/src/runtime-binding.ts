/** Owner observation transport contract. Shape validation is not authentication.
 * Caller must obtain the fixed Pin and port from a trusted owner, not unknown JSON.
 * No shared write, sync, CRDT, peer discovery or authority minting is implemented.
 */
import type {Scope,NoteState,Intent} from './types.js';
import {record,string,u64,bool,count,enumValue,scope,scopeKey,check,clone,freeze,canonical,validateState} from './validate.js';
import {prepareCommand,advanceSnapshot} from './commands.js';
export interface RuntimePin {readonly scope:Scope;readonly deviceId:string;readonly storeGeneration:string;readonly streamId:string;}
export interface RuntimeObservation extends RuntimePin {
 readonly profile:'par-reference-runtime-observation-v1';readonly sequence:string;readonly revision:string;readonly observedAt:string;
 readonly authority:{readonly state:'ACTIVE'|'CONTROL_REQUIRED'|'MEMBERSHIP_PENDING'|'EPOCH_PENDING'|'CONTROL_FORK'|'CONTROL_INVALID'|'AUTH_PERSISTENCE_UNCERTAIN';readonly controlHead:string;readonly epoch:string;readonly role:'reader'|'editor'|'none';readonly writeAuthorized:boolean;};
 readonly document:{readonly envelopeCount:number;readonly pendingCount:number;readonly envelopeSetDigest:string;readonly text:null;readonly innerValidated:false;readonly applied:false;readonly catalogComplete:false;};
 readonly operation:{readonly id:string|null;readonly state:'NOT_QUERIED'|'NOT_OBSERVED'|'OBSERVED_COMMITTED';readonly commitId:string|null;readonly receiptVerified:boolean;readonly outboxState:'pending'|'in-flight'|'retained'|'rebase-required'|null;};
 readonly capabilities:{readonly observe:true;readonly inspectOperation:true;readonly sharedCommit:false;readonly sync:false;readonly crdtApply:false;};
 readonly restoreReadOnly:boolean;readonly replicationObserved:false;readonly globalLatestProven:false;readonly productQualified:false;readonly evidenceKind:'owner-verified-local-observation';
}
function hex(v:unknown,length:number):void{string(v,length);check(v.length===length&&/^[0-9a-f]+$/.test(v),'hex identifier');}
function validatePin(v:unknown):RuntimePin{
 const p=record(v,['scope','deviceId','storeGeneration','streamId']);scope(p.scope);hex(p.scope.spaceId,64);hex(p.scope.documentId,64);hex(p.deviceId,64);hex(p.storeGeneration,32);hex(p.streamId,32);return freeze(clone(p as unknown as RuntimePin));
}
export function validateRuntimeObservation(input:unknown):RuntimeObservation{
 const r=record(input,['profile','scope','deviceId','storeGeneration','streamId','sequence','revision','observedAt','authority','document','operation','capabilities','restoreReadOnly','replicationObserved','globalLatestProven','productQualified','evidenceKind']);
 check(r.profile==='par-reference-runtime-observation-v1','profile');scope(r.scope);hex(r.scope.spaceId,64);hex(r.scope.documentId,64);hex(r.deviceId,64);hex(r.storeGeneration,32);hex(r.streamId,32);u64(r.sequence);hex(r.revision,64);string(r.observedAt,24);
 const date=new Date(r.observedAt);check(Number.isFinite(date.getTime())&&date.toISOString()===r.observedAt,'observed time');bool(r.restoreReadOnly);
 check(r.replicationObserved===false&&r.globalLatestProven===false&&r.productQualified===false&&r.evidenceKind==='owner-verified-local-observation','unsupported claim');
 const a=record(r.authority,['state','controlHead','epoch','role','writeAuthorized']);enumValue(a.state,['ACTIVE','CONTROL_REQUIRED','MEMBERSHIP_PENDING','EPOCH_PENDING','CONTROL_FORK','CONTROL_INVALID','AUTH_PERSISTENCE_UNCERTAIN']);hex(a.controlHead,64);u64(a.epoch);enumValue(a.role,['reader','editor','none']);bool(a.writeAuthorized);check(!a.writeAuthorized||(a.state==='ACTIVE'&&a.role==='editor'&&!r.restoreReadOnly),'write authority');
 const d=record(r.document,['envelopeCount','pendingCount','envelopeSetDigest','text','innerValidated','applied','catalogComplete']);count(d.envelopeCount,256);count(d.pendingCount,256);check(d.pendingCount===d.envelopeCount,'pending envelope contract');hex(d.envelopeSetDigest,64);check(d.text===null&&d.innerValidated===false&&d.applied===false&&d.catalogComplete===false,'no materialization');
 const o=record(r.operation,['id','state','commitId','receiptVerified','outboxState']);if(o.id!==null)hex(o.id,32);enumValue(o.state,['NOT_QUERIED','NOT_OBSERVED','OBSERVED_COMMITTED']);bool(o.receiptVerified);
 if(o.state==='OBSERVED_COMMITTED'){hex(o.commitId,64);check(o.id!==null&&o.receiptVerified&&d.envelopeCount>0,'receipt context');enumValue(o.outboxState,['pending','in-flight','retained','rebase-required']);}
 else {check(o.commitId===null&&o.receiptVerified===false&&o.outboxState===null,'unobserved outcome');check((o.state==='NOT_QUERIED')===(o.id===null),'query target');}
 const c=record(r.capabilities,['observe','inspectOperation','sharedCommit','sync','crdtApply']);check(c.observe===true&&c.inspectOperation===true&&c.sharedCommit===false&&c.sync===false&&c.crdtApply===false,'capabilities');
 return freeze(clone(r as unknown as RuntimeObservation));
}
function bound(input:unknown,pin:RuntimePin):RuntimeObservation{
 const r=validateRuntimeObservation(input);check(scopeKey(r.scope)===scopeKey(pin.scope)&&r.storeGeneration===pin.storeGeneration&&r.deviceId===pin.deviceId&&r.streamId===pin.streamId,'fixed owner stream/scope','RUNTIME_BINDING_MISMATCH');return r;
}
/** Construct a neutral view from actual metadata; never seed it from a synthetic UI story. */
export function projectRuntimeObservation(input:unknown,expected:unknown):NoteState{
 const p=validatePin(expected),r=bound(input,p);const a=r.authority;
 const phase:NoteState['authority']['state']=a.state==='ACTIVE'?'ready':a.state==='CONTROL_FORK'?'fork':a.state==='CONTROL_INVALID'?'denied':a.state==='EPOCH_PENDING'?'seed-pending':'pending';
 return validateState({schemaVersion:1,streamId:r.streamId,sequence:r.sequence,revision:r.revision,snapshotTime:r.observedAt,scope:r.scope,surface:'editor',
  capabilities:{host:'linux',storageClass:'native-candidate',durableKeeperEligible:false,keyProtection:'software-encrypted',supportsLocalEffectTransaction:false,background:'unsupported'},
  supportedCommands:['open-details','inspect-operation'],
  local:{state:r.operation.state==='OBSERVED_COMMITTED'?'committed':'unknown',storageClass:'native-candidate',operationId:r.operation.id,cancellationRequested:false},
  protection:{root:r.document.envelopeSetDigest,goal:0,observations:[],keys:'unknown',physicalIndependence:'unknown'},
  connection:{state:'unknown',peers:0},authority:{state:phase,controlHead:a.controlHead,epoch:a.epoch,role:a.role,sharedWriteAllowed:false},
  document:{read:r.document.envelopeCount>0?'found':'absent-local',title:'',text:'',frontier:'opaque-envelope-set:'+r.document.envelopeSetDigest,innerValidated:false,applied:false,conflicts:[],privateDraft:false,knownCatalogComplete:false,missingObjects:'0'},
  recovery:{phase:'idle',received:'0',total:null,recipientValidated:false,keys:'unknown',missingObjects:'0'},rpc:{state:'idle',operationId:null},
  invite:{phase:'none',role:'reader',targetDevice:null,manualAvailable:false,fileAvailable:false},contribution:{state:'disabled',storageBudget:'0',relayBudget:'0',activeLeases:0},presence:'unknown',diagnostic:null,previews:[],
  evidence:{kind:'runtime-observation',references:['authenticated-local-store; pending opaque envelopes, not CRDT', 'store-generation:'+r.storeGeneration, 'operation-outcome:'+r.operation.state, 'restored-read-only:'+String(r.restoreReadOnly), 'network-and-replication:not-observed']}});
}
export interface RuntimeObservationPort {observe(operationId:string|null):Promise<unknown>;inspectOperation(operationId:string):Promise<unknown>;}
export type RuntimeEffectResult={readonly outcome:'observed';readonly observation:NoteState}|{readonly outcome:'unknown'|'unavailable'};
/** A narrow effect port. Only reads/operation outcome inquiries, never mutation. */
export class RuntimeBinding {
 private readonly pin:RuntimePin;private state:NoteState;private busy=false;private closed=false;private observation:RuntimeObservation;
 constructor(expected:unknown,initial:unknown,private readonly port:RuntimeObservationPort){this.pin=validatePin(expected);this.observation=bound(initial,this.pin);this.state=projectRuntimeObservation(this.observation,this.pin);}
 get current():NoteState{return this.state;}
 close():void{this.closed=true;}
 private start():void{check(!this.closed,'closed','RUNTIME_CLOSED');check(!this.busy,'busy','RUNTIME_BUSY');this.busy=true;}
 private accept(value:unknown,operationId:string|null):NoteState{
  check(!this.closed,'closed','RUNTIME_CLOSED');const r=bound(value,this.pin);check(r.operation.id===operationId,'operation changed','OPERATION_MISMATCH');
  if(r.sequence===this.observation.sequence||r.revision===this.observation.revision)check(canonical(r)===canonical(this.observation),'observation token reused','REVISION_REUSED');
  const next=advanceSnapshot(this.state,projectRuntimeObservation(r,this.pin));this.observation=r;this.state=next;return next;
 }
 async refresh():Promise<NoteState>{this.start();try{return this.accept(await this.port.observe(this.state.local.operationId),this.state.local.operationId);}finally{this.busy=false;}}
 async execute(input:Intent):Promise<RuntimeEffectResult>{
  this.start();try{
   const i=record(input,['kind','command','effectExecuted','requiresDomainRevalidation','recoveryActivation']);check(i.kind==='intent'&&i.effectExecuted===false&&i.requiresDomainRevalidation===true&&i.recoveryActivation===null,'inert intent');
   const intent=prepareCommand(this.state,i.command);
   if(intent.command.kind!=='inspect-operation')return {outcome:'unavailable'};
   try{return {outcome:'observed',observation:this.accept(await this.port.inspectOperation(intent.command.operationId),intent.command.operationId)};}
   catch{return {outcome:'unknown'};} // Inquiry failure is NOT an operation failure; no auto retry.
  }finally{this.busy=false;}
 }
}
