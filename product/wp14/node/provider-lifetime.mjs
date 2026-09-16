/** Strict Node-side native-provider lifetime fence. No provider discovery/fallback. */
const PROFILE='par-native-provider-handoff-0056';
const fields=['profile','providerId','providerVersion','platform','epoch','protection','osProtectionProven','rollbackProtectionProven','nativeBuild','versions','capabilities','productQualified'];
const fail=code=>{throw new Error(code);};
const exact=(o,keys)=>o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join('\0')===[...keys].sort().join('\0');
const copy=value=>structuredClone(value);
export function validateDescriptor(raw){
 if(!exact(raw,fields))fail('MANIFEST_FIELDS');
 if(raw.profile!==PROFILE)fail('MANIFEST_PROFILE');
 if(typeof raw.providerId!=='string'||!raw.providerId||typeof raw.epoch!=='string'||!/^[0-9a-f]{32}$/.test(raw.epoch))fail('PROVIDER_EPOCH');
 for(const k of ['osProtectionProven','rollbackProtectionProven','productQualified'])if(typeof raw[k]!=='boolean')fail('MANIFEST_BOOL');
 if(raw.productQualified)fail('PRODUCT_QUALIFICATION_FORBIDDEN');
 if(!exact(raw.versions,['handoff','wire','suite','store','sdk','ui']))fail('VERSION_FIELDS');
 if(!exact(raw.capabilities,['pinStore','callerIntentStore','connectionFactory']))fail('CAPABILITY_NAMES');
 for(const v of Object.values(raw.capabilities)){
  if(!exact(v,['status','factorySupplied','atomicity','cancellation','resume','epochBound']))fail('CAPABILITY_FIELDS');
  if(typeof v.factorySupplied!=='boolean'||typeof v.epochBound!=='boolean')fail('MANIFEST_BOOL');
  if(v.status==='AVAILABLE'&&!v.factorySupplied)fail('CAPABILITY_FACTORY');
 }
 if(raw.nativeBuild!=='BUILD_VERIFIED'&&raw.osProtectionProven)fail('PROTECTION_UNVERIFIED');
 return copy(raw);
}
export class ProviderLifetime{
 #d;#p;#epoch;#closed=false;#cleanup=true;#closeAttempted=false;
 constructor(descriptor,port,expectedEpoch){this.#d=validateDescriptor(descriptor);if(!port||typeof port.epoch!=='function'||typeof port.observe!=='function'||typeof port.inquire!=='function'||typeof port.close!=='function')fail('PROVIDER_PORT');if(expectedEpoch!==this.#d.epoch||port.epoch()!==expectedEpoch)fail('PROVIDER_EPOCH_CHANGED');this.#p=port;this.#epoch=expectedEpoch;}
 #check(){if(this.#closed)fail('SESSION_CLOSED');if(this.#p.epoch()!==this.#epoch)fail('PROVIDER_EPOCH_CHANGED');}
 status(){return{closed:this.#closed,cleanupConfirmed:this.#cleanup,productQualified:false};}
 async observe(signal){this.#check();if(signal?.aborted)fail('CANCELLED');const value=copy(await this.#p.observe());if(signal?.aborted)fail('CANCELLED');if(this.#p.epoch()!==this.#epoch)fail('PROVIDER_EPOCH_CHANGED');return value;}
 async inquire(operationId,signal){this.#check();if(typeof operationId!=='string'||!/^[0-9a-f]{32}$/.test(operationId))fail('OPERATION_ID');const id=(''+operationId);if(signal?.aborted)fail('CANCELLED');const value=copy(await this.#p.inquire(id));if(signal?.aborted)fail('CANCELLED');if(this.#p.epoch()!==this.#epoch)fail('PROVIDER_EPOCH_CHANGED');if(value&&typeof value==='object'&&'operationId'in value&&value.operationId!==id)fail('OPERATION_ID_MISMATCH');return value;}
 async close(){if(this.#closeAttempted)return this.#cleanup;this.#closeAttempted=true;this.#closed=true;try{await this.#p.close();this.#cleanup=true;}catch{this.#cleanup=false;}return this.#cleanup;}
}
