/** A UI-facing port. A private draft receipt must never promote a shared snapshot. */
import type {Draft,Scope} from './types.js';
import {record,count,string,check,freeze,validateDraft} from './validate.js';
import {MAX_DRAFT_VERSION,validateSlot} from './draft-storage.js';
import type {LoadedDraft,PrivateDraftReceipt,PreparedDraftWrite} from './draft-vault.js';
import {DraftVault,DraftError} from './draft-vault.js';
export interface DraftSessionPort {
 readonly scope:Scope;
 load():Promise<LoadedDraft>;
 save(draft:Draft,version:number,operationId:string):Promise<PrivateDraftReceipt>;
 reconcile():Promise<'CONFIRMED'|'NOT_CONFIRMED'|'SUPERSEDED'>;
 close():void;
}
export class VaultDraftSession implements DraftSessionPort {
 #pending:PreparedDraftWrite|null=null; #busy=false;
 constructor(readonly vault:DraftVault) {}
 get scope():Scope{return this.vault.scope;}
 load():Promise<LoadedDraft>{return this.vault.load();}
 async save(draft:Draft,version:number,operationId:string):Promise<PrivateDraftReceipt>{
  if(this.#busy||this.#pending)throw new DraftError('DRAFT_RECONCILE_REQUIRED');
  this.#busy=true;
  try{
   this.#pending=await this.vault.prepare(draft,version,operationId);
   const result=await this.vault.commit(this.#pending);this.#pending=null;return result;
  }catch(e){if(!(e instanceof DraftError&&e.code==='DRAFT_WRITE_UNKNOWN'))this.#pending=null;throw e;}
  finally{this.#busy=false;}
 }
 async reconcile():Promise<'CONFIRMED'|'NOT_CONFIRMED'|'SUPERSEDED'>{
  if(this.#busy)throw new DraftError('DRAFT_BUSY');
  if(!this.#pending)throw new DraftError('NO_PENDING_DRAFT');
  this.#busy=true;
  try{const result=await this.vault.inspect(this.#pending);this.#pending=null;return result.state;}
  finally{this.#busy=false;}
 }
 close():void{this.vault.close();}
}

/** Structural validation of a trusted host observation, not a cryptographic receipt. */
export function checkDraftLoad(input:unknown):LoadedDraft {
 const x=record(input,['version','operationId','draft']);count(x.version,MAX_DRAFT_VERSION);
 if(x.version===0){check(x.operationId===null&&x.draft===null,'empty draft store');}
 else string(x.operationId);
 return freeze({version:x.version,operationId:x.operationId as string|null,draft:x.draft===null?null:validateDraft(x.draft)});
}
export function checkDraftReceipt(input:unknown,version:number,operationId:string):PrivateDraftReceipt {
 const x=record(input,['version','operationId','slot','ciphertextHash','durability','sharedSaved','replicated']);
 count(x.version,MAX_DRAFT_VERSION);check(x.version===version+1&&x.operationId===operationId,'draft operation binding');
 validateSlot(x.slot);validateSlot(x.ciphertextHash);check(x.sharedSaved===false&&x.replicated===false,'local draft only');
 check(x.durability==='browser-best-effort'||x.durability==='posix-fsync-candidate','storage capability');
 return freeze({...x} as unknown as PrivateDraftReceipt);
}
