/** POSIX caller-owned immutable intent slot + one-use dispatch marker.
 * Synchronous filesystem operations finish before a Promise resolves. Metadata is
 * NOT encrypted. This is NOT a hardware/OS anti-rollback provider. One trusted
 * owner per directory; no cleanup, re-enrolment or removal after uncertainty.
 */
import * as fs from 'node:fs';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {validateOriginalApplication} from '../lib/application-owner.js';
import {canonical,ContractError} from '../lib/validate.js';
const fail=code=>{throw new ContractError(code);};
const digest=data=>createHash('sha256').update(data).digest('hex');
export class LocalCallerIntent {
 #root;#identity;#known=null;#attempted=false;
 constructor(root){if(typeof root!=='string'||!root||process.platform==='win32'||!fs.constants.O_NOFOLLOW)fail('CALLER_POSIX_REQUIRED');this.#root=resolve(root);}
 #directory(){
  const s=fs.lstatSync(this.#root);
  if(!s.isDirectory()||s.isSymbolicLink()||(s.mode&0o777)!==0o700||s.uid!==process.getuid()||fs.realpathSync(this.#root)!==this.#root)fail('CALLER_UNSAFE_PATH');
  const id=`${s.dev}:${s.ino}`;if(this.#identity&&this.#identity!==id)fail('CALLER_DIRECTORY_REPLACED');this.#identity=id;
  const names=fs.readdirSync(this.#root);if(names.some(n=>!['original.json','dispatch.json'].includes(n)))fail('CALLER_LAYOUT_UNCERTAIN');
 }
 #syncDirectory(){const fd=fs.openSync(this.#root,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_DIRECTORY);try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
 #read(name){
  let fd;try{fd=fs.openSync(join(this.#root,name),fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);}catch(e){if(e.code==='ENOENT')return null;throw e;}
  try{const s=fs.fstatSync(fd);if(!s.isFile()||s.nlink!==1||s.uid!==process.getuid()||(s.mode&0o777)!==0o600||s.size<=0||s.size>16384)fail('CALLER_UNSAFE_FILE');
   const raw=fs.readFileSync(fd);if(raw.length!==s.size||raw.length>16384)fail('CALLER_STORE_UNCERTAIN');
   const text=new TextDecoder('utf-8',{fatal:true}).decode(raw),value=JSON.parse(text);if(canonical(value)!==text)fail('CALLER_STORE_CORRUPT');
   fs.fsyncSync(fd);return{value,raw};
  }finally{fs.closeSync(fd);}
 }
 #load(){
  this.#directory();const a=this.#read('original.json'),b=this.#read('dispatch.json');
  if(a===null){if(b!==null||this.#known!==null)fail('CALLER_INTENT_MISSING');return null;}
  const original=validateOriginalApplication(a.value),sha=digest(a.raw);
  if(this.#known!==null&&this.#known!==sha)fail('CALLER_INTENT_CONFLICT');
  if(b!==null&&canonical(b.value)!==canonical({profile:'par-caller-dispatch-0052',operationId:original.operationId,originalDigest:sha}))fail('CALLER_MARKER_CONFLICT');
  if(this.#attempted&&b===null)fail('CALLER_MARKER_MISSING');
  this.#syncDirectory();this.#known=sha;this.#attempted=b!==null;return{original,dispatchAttempted:b!==null};
 }
 async load(){return this.#load();}
 #create(name,value){
  const raw=Buffer.from(canonical(value));if(raw.length>16384)fail('CALLER_STORE_BUDGET');
  const fd=fs.openSync(join(this.#root,name),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
  try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,raw);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  this.#syncDirectory();
 }
 async save(value){
  const original=validateOriginalApplication(value);const old=this.#load();
  if(old){if(canonical(old.original)!==canonical(original))fail('CALLER_INTENT_CONFLICT');return;}
  // Partial or uncertain create is retained, never deleted as a retry tactic.
  this.#create('original.json',original);
  const r=this.#load();if(!r||canonical(r.original)!==canonical(original))fail('CALLER_STORE_UNCERTAIN');
 }
 async markDispatch(operationId){
  const r=this.#load();if(!r||r.original.operationId!==operationId)fail('ORIGINAL_OPERATION_REQUIRED');
  if(r.dispatchAttempted)fail('CALLER_DISPATCH_ALREADY_RECORDED');
  this.#create('dispatch.json',{profile:'par-caller-dispatch-0052',operationId,originalDigest:this.#known});
  const checked=this.#load();if(!checked?.dispatchAttempted)fail('CALLER_STORE_UNCERTAIN');
 }
}
