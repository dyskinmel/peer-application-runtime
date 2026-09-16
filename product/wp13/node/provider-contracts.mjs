/** Explicit disposable provider contract. No provider discovery or fallback.
 * Passing does not prove OS protection, hardware counters or rollback resistance.
 */
import {validateOriginalApplication} from '../../wp11/lib/application-owner.js';
import {canonical} from '../../wp11/lib/validate.js';
const require=(v,c)=>{if(!v)throw new Error(c);};
export async function callerConformance(factory,value){
 if(factory===null||factory===undefined)return{result:'BLOCKED',reason:'CALLER_PROVIDER_NOT_SUPPLIED',checks:[],osProtectionProven:false};
 require(typeof factory==='function','CONFORMANCE_FACTORY');const original=validateOriginalApplication(value);const checks=[];
 const open=()=>{const p=factory();require(p&&['load','save','markDispatch'].every(k=>typeof p[k]==='function'),'CONFORMANCE_PROVIDER');return p;};
 const check=async(p,attempted,code)=>{const r=await p.load();require(r!==null&&canonical(r.original)===canonical(original)&&r.dispatchAttempted===attempted,code);};
 const reject=async(fn,code)=>{try{await fn();}catch(e){require(e.code===code,'CONFORMANCE_ERROR_CLASS');return;}throw new Error('CONFORMANCE_REJECTION_MISSING');};
 let p=open();require(await p.load()===null,'CONFORMANCE_EMPTY_NAMESPACE_REQUIRED');checks.push('empty');
 await p.save(original);await check(p,false,'CONFORMANCE_SAVE_READBACK');checks.push('save');
 p=open();await check(p,false,'CONFORMANCE_REOPEN');checks.push('reopen');
 await p.save(original);await check(p,false,'CONFORMANCE_SAME_INTENT');checks.push('idempotent_save');
 const other={...original,operationId:original.operationId==='70'.repeat(16)?'71'.repeat(16):'70'.repeat(16)};
 await reject(()=>p.save(other),'CALLER_INTENT_CONFLICT');checks.push('conflict');
 await p.markDispatch(original.operationId);await check(p,true,'CONFORMANCE_MARKER_READBACK');p=open();await check(p,true,'CONFORMANCE_MARKER_REOPEN');checks.push('marker');
 await reject(()=>p.markDispatch(original.operationId),'CALLER_DISPATCH_ALREADY_RECORDED');await check(p,true,'CONFORMANCE_MARKER_LOST');checks.push('no_second_dispatch');
 return{result:'PASS',checks,osProtectionProven:false,scope:'DISPOSABLE_PROVIDER_CONTRACT_ONLY'};
}
