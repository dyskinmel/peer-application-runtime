/** Actual-Automerge adapter candidate. No synthetic merge implementation.
 * All source changes are rechecked on their causal view, then materialized on
 * the exact union. The package is pinned by the caller; this is not a sandbox.
 */
import {CoreError,PROFILE as CHANGE_PROFILE,bytes,checkSingleChunk,checkText,digest,metadata,validateWithCore} from './automerge.mjs';
export const PROFILE='par-document-apply-local-0035';
const need=(ok,code='CORE_REPORT_INVALID')=>{if(!ok)throw new CoreError(code);};
const hex=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x);
const exact=(o,keys)=>o&&typeof o==='object'&&!Array.isArray(o)&&Object.getPrototypeOf(o)===Object.prototype&&Object.keys(o).sort().join(',')===[...keys].sort().join(',');
export function validateMaterializationRequest(q){
 need(exact(q,['profile','schema','changes','expectedHeads'])&&q.profile===PROFILE&&q.schema==='note-v1-local');
 need(Array.isArray(q.changes)&&q.changes.length>0&&q.changes.length<=128,'RESOURCE_LIMIT');
 const known=new Set(),slots=new Set(),parents=new Set();let n=0;
 for(const x of q.changes){
  need(exact(x,['actor','sequence','hash','dependencies','change'])&&hex(x.actor)&&hex(x.hash));
  need(typeof x.sequence==='string'&&/^[1-9][0-9]*$/.test(x.sequence)&&Number.isSafeInteger(Number(x.sequence)),'UNSUPPORTED_INTEGER_RANGE');
  need(Array.isArray(x.dependencies)&&x.dependencies.length<=128&&x.dependencies.every(hex)&&new Set(x.dependencies).size===x.dependencies.length);
  need(x.dependencies.every(d=>known.has(d)),'DEPENDENCIES_MISSING');
  need(!known.has(x.hash)&&!slots.has(x.actor+':'+x.sequence),'ACTOR_EQUIVOCATION');
  const raw=bytes(x.change);checkSingleChunk(raw);n+=raw.length;need(n<=4*1024*1024,'RESOURCE_LIMIT');
  known.add(x.hash);slots.add(x.actor+':'+x.sequence);x.dependencies.forEach(d=>parents.add(d));
 }
 need(Array.isArray(q.expectedHeads)&&q.expectedHeads.every(hex)&&new Set(q.expectedHeads).size===q.expectedHeads.length);
 need(JSON.stringify([...known].filter(x=>!parents.has(x)).sort())===JSON.stringify([...q.expectedHeads].sort()),'FRONTIER_MISMATCH');
 return q;
}
export function materializeWithCore(core,q){
 validateMaterializationRequest(q);const A=core.A,byHash=new Map(q.changes.map(x=>[x.hash,x]));
 let doc=A.init({actor:'f'.repeat(64)});
 try{
  for(const change of q.changes){
   const ancestors=new Set();function visit(h){if(ancestors.has(h))return;const n=byHash.get(h);need(n,'DEPENDENCIES_MISSING');n.dependencies.forEach(visit);ancestors.add(h);}
   change.dependencies.forEach(visit);
   validateWithCore(core,{profile:CHANGE_PROFILE,schema:q.schema,candidate:change,closure:q.changes.filter(x=>ancestors.has(x.hash))});
   [doc]=A.applyChanges(doc,[bytes(change.change)]);
  }
  const all=A.getChangesMetaSince(doc,[]).map(metadata),expected=q.changes.map(x=>({actor:x.actor,sequence:x.sequence,hash:x.hash,dependencies:[...x.dependencies].sort()}));
  need(digest([...all].sort((x,y)=>x.hash.localeCompare(y.hash)))===digest([...expected].sort((x,y)=>x.hash.localeCompare(y.hash))),'APPLIED_SET_MISMATCH');
  const heads=[...A.getHeads(doc)].sort();need(JSON.stringify(heads)===JSON.stringify([...q.expectedHeads].sort()),'FRONTIER_MISMATCH');need(A.getMissingDeps(doc,[]).length===0,'DEPENDENCIES_MISSING');
  need(Object.keys(doc).sort().join(',')==='body,title'&&A.isImmutableString(doc.title)&&typeof doc.body==='string','UNSUPPORTED_NOTE_SCHEMA');
  const bodyConflicts=A.getConflicts(doc,'body');need(!bodyConflicts||Object.keys(bodyConflicts).length<=1,'TEXT_OBJECT_CONFLICT_UNSUPPORTED');
  const title=checkText(String(doc.title),1024),body=checkText(doc.body,262144);
  const titleConflicts=Object.values(A.getConflicts(doc,'title')??{}).map(x=>{need(A.isImmutableString(x),'UNSUPPORTED_NOTE_SCHEMA');return checkText(String(x),1024);}).sort();need(titleConflicts.length<=32,'RESOURCE_LIMIT');
  return {profile:PROFILE,requestDigest:digest(q),engine:core.identity,schema:q.schema,changes:expected,appliedHashes:all.map(x=>x.hash).sort(),heads,missing:[],note:{title,body,titleConflicts}};
 }finally{A.free(doc);}
}
