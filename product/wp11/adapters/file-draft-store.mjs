/** Node/POSIX candidate. An explicit private root, bounded files and cooperative CAS.
 * No key files; no implicit stale-lock removal; same-user hostile access is out of scope.
 */
import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {DraftError,validateRow,validateSlot,parseRow,MAX_DRAFT_ROW_BYTES} from '../lib/draft-storage.js';
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
function requirePosix(){if(typeof process.getuid!=='function')throw new DraftError('POSIX_REQUIRED');}
async function privateDirectory(dir){requirePosix();const s=await fs.lstat(dir);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&0o777)!==0o700)throw new DraftError('PRIVATE_DIRECTORY_REQUIRED');return s;}
async function syncDirectory(dir){const f=await fs.open(dir,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);try{await f.sync();}finally{await f.close();}}
async function readPrivate(file,limit=MAX_DRAFT_ROW_BYTES+1024){
 let f;try{f=await fs.open(file,constants.O_RDONLY|constants.O_NOFOLLOW);}catch(e){if(e.code==='ENOENT')return null;throw e;}
 try{const a=await f.stat();if(!a.isFile()||a.nlink!==1||a.uid!==process.getuid()||(a.mode&0o777)!==0o600||a.size>limit)throw new DraftError('PRIVATE_FILE_REQUIRED');const buffer=Buffer.alloc(a.size+1);let used=0;while(used<buffer.length){const r=await f.read(buffer,used,buffer.length-used,used);if(r.bytesRead===0)break;used+=r.bytesRead;}const bytes=buffer.subarray(0,used);const b=await f.stat(),c=await fs.lstat(file);if(a.ino!==b.ino||a.dev!==b.dev||a.size!==bytes.length||a.size!==b.size||a.mtimeMs!==b.mtimeMs||a.ctimeMs!==b.ctimeMs||c.ino!==b.ino||c.dev!==b.dev||c.isSymbolicLink())throw new DraftError('FILE_CHANGED');return bytes.toString('utf8');}finally{await f.close();}
}
export class FileDraftStore {
 durability='posix-fsync-candidate';
 constructor(directory,{boundary=()=>{}}={}){if(typeof directory!=='string'||!path.isAbsolute(directory))throw new DraftError('ABSOLUTE_PRIVATE_ROOT_REQUIRED');this.directory=directory;this.boundary=boundary;}
 async read(slot){validateSlot(slot);await privateDirectory(this.directory);const text=await readPrivate(path.join(this.directory,slot+'.json'));return text===null?null:parseRow(text);}
 async compareAndSwap(slot,expectedVersion,next){
  validateSlot(slot);const row=validateRow(next);if(!Number.isSafeInteger(expectedVersion)||expectedVersion<0||row.version!==expectedVersion+1)throw new DraftError('INVALID_VERSION');
  await privateDirectory(this.directory);const token=randomUUID();const lock=path.join(this.directory,'.writer.lock');let handle;
  try{handle=await fs.open(lock,constants.O_CREAT|constants.O_EXCL|constants.O_WRONLY|constants.O_NOFOLLOW,0o600);}catch(e){if(e.code==='EEXIST')throw new DraftError('WRITER_ACTIVE');throw e;}
  const temporary=path.join(this.directory,'.draft-'+token+'.tmp');let failure=null;
  try{
   await handle.writeFile(canonical({schema:1,pid:process.pid,token}));await handle.sync();await syncDirectory(this.directory);
   const existing=await this.read(slot);if((existing?.version??0)!==expectedVersion)throw new DraftError('DRAFT_CONFLICT');
   let count=0,bytes=0;
   for(const n of await fs.readdir(this.directory))if(/^[a-f0-9]{64}\.json$/.test(n)){count++;const s=await fs.lstat(path.join(this.directory,n));bytes+=s.size;}
   const data=canonical(row);if((existing===null&&count>=32)||bytes+Buffer.byteLength(data)>64*1024*1024)throw new DraftError('DRAFT_QUOTA');
   const f=await fs.open(temporary,constants.O_CREAT|constants.O_EXCL|constants.O_WRONLY|constants.O_NOFOLLOW,0o600);
   try{await f.writeFile(data);await f.sync();}finally{await f.close();}
   this.boundary('temp-synced');
   await privateDirectory(this.directory);
   const again=await this.read(slot);if(canonical(again)!==canonical(existing))throw new DraftError('DRAFT_CONFLICT');
   await fs.rename(temporary,path.join(this.directory,slot+'.json'));this.boundary('published');
   await syncDirectory(this.directory);this.boundary('directory-synced');
  }catch(e){failure=e;throw e;}
  finally{
   let cleanupError=null;
   try{await handle.close();}catch(e){cleanupError=e;}
   try{await fs.unlink(temporary);}catch(e){if(e.code!=='ENOENT')cleanupError??=e;}
   try{const text=await readPrivate(lock,1024);if(text!==canonical({schema:1,pid:process.pid,token}))throw new DraftError('LOCK_CHANGED');await fs.unlink(lock);await syncDirectory(this.directory);}catch(e){cleanupError??=e;}
   // Preserve the primary failure, but never report success when cleanup is uncertain.
   if(!failure&&cleanupError)throw cleanupError;
  }
 }
 static async recoverLock(directory){
  await privateDirectory(directory);const lock=path.join(directory,'.writer.lock');const before=await fs.lstat(lock);const text=await readPrivate(lock,1024);if(text===null)throw new DraftError('LOCK_MISSING');
  let obj;try{obj=JSON.parse(text);}catch{throw new DraftError('LOCK_INVALID');}
  if(!Number.isSafeInteger(obj.pid)||obj.pid<=0)throw new DraftError('LOCK_INVALID');
  try{process.kill(obj.pid,0);throw new DraftError('WRITER_ACTIVE');}catch(e){if(e.code!=='ESRCH')throw e;}
  if(obj.schema!==1||typeof obj.token!=='string'||!/^[0-9a-f-]{36}$/.test(obj.token)||canonical(obj)!==text)throw new DraftError('LOCK_INVALID');
  const now=await fs.lstat(lock);if(now.ino!==before.ino||now.dev!==before.dev||await readPrivate(lock,1024)!==text)throw new DraftError('LOCK_CHANGED');
  const temporary=path.join(directory,'.draft-'+obj.token+'.tmp');const data=await readPrivate(temporary);if(data!==null)await fs.unlink(temporary);
  await fs.unlink(lock);await syncDirectory(directory);
  return {recovered:true,deadPid:obj.pid,automatic:false};
 }
}
