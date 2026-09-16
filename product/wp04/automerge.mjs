/** Pinned Automerge 3.4.1 adapter CANDIDATE. No bundled engine or substitute merge.
 * Real-engine execution is a separate required probe; contract tests alone do
 * not qualify it. Owner-selected package code is trusted code, not sandboxed.
 */
import {createHash} from 'node:crypto';
import {lstatSync,readFileSync,readdirSync,realpathSync} from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
export const PROFILE='par-shared-change-local-0032';
export class CoreError extends Error {constructor(code){super(code);this.code=code;}}
const need=(x,code='INVALID_INPUT')=>{if(!x)throw new CoreError(code);};
const hex=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
function plain(x){need(x!==null&&typeof x==='object'&&Object.getPrototypeOf(x)===Object.prototype);for(const d of Object.values(Object.getOwnPropertyDescriptors(x)))need('value'in d);return x;}
function stable(x){if(Array.isArray(x))return '['+x.map(stable).join(',')+']';if(x!==null&&typeof x==='object'){plain(x);return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+stable(x[k])).join(',')+'}';}need(x===null||typeof x==='string'||typeof x==='boolean'||(typeof x==='number'&&Number.isFinite(x)));return JSON.stringify(x);}
export const digest=x=>createHash('sha256').update(stable(x)).digest('hex');
const sha=x=>createHash('sha256').update(x).digest('hex');
export function uint(x){need(typeof x==='number'&&Number.isSafeInteger(x)&&x>=0,'UNSUPPORTED_INTEGER_RANGE');return x;}
export function checkText(x,limit){need(typeof x==='string');need(Buffer.from(x,'utf8').toString('utf8')===x);need(Buffer.byteLength(x)<=limit,'RESOURCE_LIMIT');return x;}
export function bytes(s){need(typeof s==='string'&&s.length<=699052,'RESOURCE_LIMIT');need(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(s));const b=Buffer.from(s,'base64');need(b.toString('base64')===s);return b;}
export function checkSingleChunk(b){
 need(b instanceof Uint8Array&&b.length<=524288,'RESOURCE_LIMIT');need(b.length>=10&&Buffer.from(b.subarray(0,4)).equals(Buffer.from([0x85,0x6f,0x4a,0x83])),'NOT_SINGLE_CHANGE');
 if(b[8]===2)throw new CoreError('COMPRESSED_CHANGE_UNSUPPORTED');need(b[8]===1,'NOT_SINGLE_CHANGE');
 let n=0,scale=1,i=9,count=0,last;
 do {need(i<b.length&&count<4,'NOT_SINGLE_CHANGE');last=b[i++];n+=(last&127)*scale;scale*=128;count++;} while(last&128);
 need(!(count>1&&(last&127)===0)&&n>0&&n+i===b.length,'NOT_SINGLE_CHANGE');return true;
}
export function metadata(m){
 plain(m);need(hex(m.actor)&&hex(m.hash));uint(m.seq);need(m.seq>=1);need(Array.isArray(m.deps)&&m.deps.length<=128&&m.deps.every(hex)&&new Set(m.deps).size===m.deps.length);
 return {actor:m.actor,sequence:String(m.seq),hash:m.hash,dependencies:[...m.deps].sort()};
}
export function validatePackageInfo(p){
 plain(p);need(p.name==='@automerge/automerge'&&p.version==='3.4.1','CORE_VERSION_UNSUPPORTED');need(p.license==='MIT','CORE_LICENSE_UNREVIEWED');
 for(const k of ['dependencies','optionalDependencies','peerDependencies'])need(!p[k]||Object.keys(p[k]).length===0,'UNPINNED_TRANSITIVE_DEPENDENCIES');return true;
}
export function packageInventory(root,entry='dist/cjs/fullfat_node.cjs'){
 need(typeof root==='string'&&path.isAbsolute(root),'CORE_MANIFEST_INVALID');need(!lstatSync(root).isSymbolicLink()&&lstatSync(root).isDirectory(),'CORE_MANIFEST_INVALID');
 need(entry==='dist/cjs/fullfat_node.cjs','CORE_ENTRY_UNSUPPORTED');const records=[];const folded=new Set();let total=0;
 function walk(base){for(const name of readdirSync(base).sort()){
  const p=path.join(base,name),s=lstatSync(p),rel=path.relative(root,p).split(path.sep).join('/');need(!s.isSymbolicLink(),'CORE_UNSAFE_PATH');
  if(s.isDirectory()){need(name!=='node_modules'&&name!=='.git','UNPINNED_TRANSITIVE_DEPENDENCIES');walk(p);continue;}
  need(s.isFile()&&s.nlink===1&&s.size<=64*1024*1024,'CORE_UNSAFE_PATH');need(!folded.has(rel.toLowerCase()),'CORE_UNSAFE_PATH');folded.add(rel.toLowerCase());
  total+=s.size;need(total<=128*1024*1024&&records.length<4096,'RESOURCE_LIMIT');records.push({path:rel,size:s.size,sha256:sha(readFileSync(p))});
 }}walk(root);records.sort((a,b)=>a.path<b.path?-1:1);
 const p=JSON.parse(readFileSync(path.join(root,'package.json'),'utf8'));validatePackageInfo(p);need(records.some(r=>r.path===entry),'CORE_ENTRY_UNSUPPORTED');
 return {profile:PROFILE,packageRoot:realpathSync(root),entry,name:p.name,version:p.version,license:p.license,files:records,digest:digest(records)};
}
export function verifyManifest(file){
 try{
  need(typeof file==='string'&&path.isAbsolute(file),'CORE_MANIFEST_INVALID');const s=lstatSync(file);need(s.isFile()&&!s.isSymbolicLink()&&s.size<=1024*1024,'CORE_MANIFEST_INVALID');
  const m=JSON.parse(readFileSync(file,'utf8'));plain(m);need(Object.keys(m).sort().join(',')===['profile','packageRoot','entry','name','version','license','files','digest'].sort().join(','),'CORE_MANIFEST_INVALID');
  const actual=packageInventory(m.packageRoot,m.entry);need(stable(actual)===stable(m),'CORE_ARTIFACT_CHANGED');return actual;
 }catch(e){if(e instanceof CoreError)throw e;throw new CoreError(e.code==='ENOENT'?'CORE_UNAVAILABLE':'CORE_MANIFEST_INVALID');}
}
export async function loadPinnedCore(manifestPath){
 const manifest=verifyManifest(manifestPath);
 const loaded=await import(pathToFileURL(path.join(manifest.packageRoot,manifest.entry)).href);const A=loaded.default??loaded;
 for(const name of ['init','from','clone','change','splice','getAllChanges','getChangesMetaSince','inspectChange','getHeads','getMissingDeps','getObjectId','applyChanges','getLastLocalChange','view','free','merge','getConflicts','isImmutableString','releaseInfo'])need(typeof A[name]==='function','CORE_API_MISMATCH');
 need(typeof A.ImmutableString==='function','CORE_API_MISMATCH');const release=A.releaseInfo();
 need(release?.js?.version==='3.4.1'&&release?.wasm&&typeof release.js.gitHead==='string'&&release.js.gitHead.length>=7&&release.js.gitHead===release.wasm.gitHead,'CORE_BUILD_MISMATCH');
 verifyManifest(manifestPath);
 return {A,identity:{name:manifest.name,version:manifest.version,kind:'automerge',digest:manifest.digest},manifest,release};
}
export function validateOps(ops,bodyId,meta){
 need(Array.isArray(ops)&&ops.length>0&&ops.length<=4096,'UNSUPPORTED_NOTE_OPERATION');let current=bodyId;
 need(hex(meta.actor));uint(meta.startOp);
 for(let i=0;i<ops.length;i++){
  const o=plain(ops[i]);need(Object.keys(o).every(k=>['action','obj','key','elemId','insert','value','datatype','pred'].includes(k)),'UNSUPPORTED_NOTE_OPERATION');
  need(Array.isArray(o.pred)&&o.pred.length<=4096&&o.pred.every(x=>typeof x==='string'),'UNSUPPORTED_NOTE_OPERATION');
  if(o.obj==='_root'){
   if(o.action==='set'&&o.key==='title'&&o.insert===false){need(o.datatype===undefined||o.datatype==='str','UNSUPPORTED_NOTE_OPERATION');checkText(o.value,1024);}
   else if(o.action==='makeText'&&o.key==='body'&&o.insert===false&&current===null){current=`${meta.startOp+i}@${meta.actor}`;}
   else throw new CoreError('UNSUPPORTED_NOTE_OPERATION');
  }else{
   need(typeof current==='string'&&o.obj===current,'UNSUPPORTED_NOTE_OPERATION');
   if(o.action==='set'&&o.insert===true){checkText(o.value,8);need([...o.value].length===1&&(o.datatype===undefined||o.datatype==='str'),'UNSUPPORTED_NOTE_OPERATION');}
   else need(o.action==='del'&&o.insert===false,'UNSUPPORTED_NOTE_OPERATION');
  }
 }return true;
}
function descriptor(x){
 plain(x);need(Object.keys(x).sort().join(',')===['actor','sequence','hash','dependencies','change'].sort().join(','));
 need(hex(x.actor)&&hex(x.hash)&&typeof x.sequence==='string'&&/^[1-9][0-9]*$/.test(x.sequence));uint(Number(x.sequence));
 need(Array.isArray(x.dependencies)&&x.dependencies.length<=128&&x.dependencies.every(hex)&&new Set(x.dependencies).size===x.dependencies.length);checkSingleChunk(bytes(x.change));return x;
}
function expectedMeta(x){return {actor:x.actor,sequence:x.sequence,hash:x.hash,dependencies:[...x.dependencies].sort()};}
function readNote(A,doc){
 need(Object.keys(doc).sort().join(',')==='body,title','UNSUPPORTED_NOTE_SCHEMA');
 need(A.isImmutableString(doc.title)&&typeof doc.body==='string','UNSUPPORTED_NOTE_SCHEMA');const title=String(doc.title);checkText(title,1024);checkText(doc.body,1024*1024);
 const bodies=A.getConflicts(doc,'body');need(!bodies||Object.keys(bodies).length<=1,'TEXT_OBJECT_CONFLICT_UNSUPPORTED');
 const conflict=A.getConflicts(doc,'title')??{};const values=Object.values(conflict).map(x=>{need(A.isImmutableString(x),'UNSUPPORTED_NOTE_SCHEMA');return checkText(String(x),1024);}).sort();need(values.length<=32,'RESOURCE_LIMIT');
 return {title,body:doc.body,titleConflicts:values};
}
function applyOne(A,doc,x){
 descriptor(x);const known=A.getChangesMetaSince(doc,[]).map(metadata);const knownSet=new Set(known.map(x=>x.hash));need(x.dependencies.every(d=>knownSet.has(d)),'DEPENDENCIES_MISSING');
 need(!knownSet.has(x.hash),'CHANGE_ALREADY_PRESENT');need(!known.some(m=>m.actor===x.actor&&m.sequence===x.sequence),'ACTOR_EQUIVOCATION');
 // Validate on exactly the declared causal view, not arrival-order global state.
 const causal=A.view(doc,x.dependencies);const bodyId=A.getObjectId(causal,'body');let isolated=A.clone(causal);let next;
 try{
  [isolated]=A.applyChanges(isolated,[bytes(x.change)]);need(A.getMissingDeps(isolated,[]).length===0,'DEPENDENCIES_MISSING');
  const added=A.getChangesMetaSince(isolated,x.dependencies).map(metadata);need(added.length===1,'NOT_SINGLE_CHANGE');need(stable(added[0])===stable(expectedMeta(x)),'INNER_OUTER_MISMATCH');
  const details=A.inspectChange(isolated,x.hash);need(details!==null,'CORE_REPORT_INVALID');validateOps(details.ops,bodyId,details);readNote(A,isolated);
  next=A.clone(doc);[next]=A.applyChanges(next,[bytes(x.change)]);need(A.getMissingDeps(next,[]).length===0,'DEPENDENCIES_MISSING');
  return next;
 }catch(e){if(next)A.free(next);throw e;}finally{A.free(isolated);}
}
export function validateWithCore(core,request){
 plain(request);need(request.profile===PROFILE&&request.schema==='note-v1-local');need(Array.isArray(request.closure)&&request.closure.length<=128,'RESOURCE_LIMIT');
 let size=bytes(request.candidate.change).length;for(const d of request.closure)size+=bytes(d.change).length;need(size<=4*1024*1024,'RESOURCE_LIMIT');
 const A=core.A;let doc=A.init({actor:'f'.repeat(64)});
 try{
  for(const x of [...request.closure,request.candidate]){const next=applyOne(A,doc,x);A.free(doc);doc=next;}
  const all=A.getChangesMetaSince(doc,[]).map(metadata);need(all.length===request.closure.length+1,'APPLIED_SET_MISMATCH');
  const one=A.inspectChange(doc,request.candidate.hash);return {profile:PROFILE,requestDigest:digest(request),engine:core.identity,changes:[metadata(one)],appliedHashes:all.map(x=>x.hash).sort(),missing:[],note:readNote(A,doc),schema:'note-v1-local'};
 }finally{A.free(doc);}
}

export function cloneForAuthor(A,doc,actor){need(hex(actor),'INVALID_ACTOR');return A.clone(doc,{actor});}
function scalarIndex(text,n){uint(n);const chars=[...text];need(n<=chars.length);return chars.slice(0,n).join('').length;}
function encoding(A){
 let d=A.from({text:'a😀b'},{actor:'e'.repeat(64)});
 try{d=A.change(d,{time:0},x=>A.splice(x,['text'],3,1,'Z'));if(d.text==='a😀Z')return 'utf16';}catch{}finally{A.free(d);}
 d=A.from({text:'a😀b'},{actor:'e'.repeat(64)});
 try{d=A.change(d,{time:0},x=>A.splice(x,['text'],2,1,'Z'));need(d.text==='a😀Z','TEXT_INDEX_UNSUPPORTED');return 'unicode-scalar';}finally{A.free(d);}
}
export function makeWithCore(core,input){
 const A=core.A;plain(input);need(hex(input.actor));let doc=A.init({actor:input.actor});
 try{
  need(Array.isArray(input.closure)&&input.closure.length<=128);for(const x of input.closure){const next=applyOne(A,doc,x);A.free(doc);doc=next;}
  need(stable([...A.getHeads(doc)].sort())===stable([...input.expectedHeads].sort()),'STALE_FRONTIER');
  // clone() otherwise allocates an unrelated actor. Only the creation clone is writable.
  const authored=cloneForAuthor(A,doc,input.actor);A.free(doc);doc=authored;
  const before=A.getHeads(doc);
  if(input.kind==='create'){
   need(before.length===0,'DOCUMENT_EXISTS');checkText(input.title,1024);checkText(input.body,262144);
   doc=A.change(doc,{time:0},d=>{d.title=new A.ImmutableString(input.title);d.body=input.body;});
  }else{
   need(input.kind==='splice'&&before.length>0);checkText(input.text,262144);uint(input.index);uint(input.deleteCount);
   const body=doc.body;need(typeof body==='string');const start=scalarIndex(body,input.index),end=scalarIndex(body,input.index+input.deleteCount);const unit=encoding(A);
   doc=A.change(doc,{time:0},d=>A.splice(d,['body'],unit==='utf16'?start:input.index,unit==='utf16'?end-start:input.deleteCount,input.text));
  }
  const changed=A.getChangesMetaSince(doc,before).map(metadata);need(changed.length===1,'NO_SINGLE_LOCAL_CHANGE');need(changed[0].actor===input.actor,'GENERATED_ACTOR_MISMATCH');
  const raw=A.getLastLocalChange(doc);need(raw!==undefined&&raw!==null);checkSingleChunk(raw);
  const result={...changed[0],change:Buffer.from(raw).toString('base64')};
  validateWithCore(core,{profile:PROFILE,schema:'note-v1-local',candidate:result,closure:input.closure});
  return result;
 }finally{A.free(doc);}
}
