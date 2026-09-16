/** Executable local demo: real encrypted SQLite journal in a child Python owner.
 * Uses only the PUBLIC SYNTHETIC fixtures. No production secrets/network. */
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {EventSubscription,LatestSnapshots} from '../product/wp10/lib/index.js';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const data=mkdtempSync(path.join(tmpdir(),'par-sdk-demo-'));
const child=spawn(process.env.PAR_PYTHON||'python3',['-I','-S','-B',path.join(root,'tests/product/event-binding/owner_worker.py'),data],{cwd:root,stdio:['pipe','pipe','inherit']});
let readyResolve,readyReject;const ready=new Promise((r,j)=>{readyResolve=r;readyReject=j});let serial=0;const waiting=new Map();
const lines=createInterface({input:child.stdout});lines.on('line',line=>{const x=JSON.parse(line);if(x.ready){readyResolve(x);return}const w=waiting.get(x.id);if(!w)return;waiting.delete(x.id);clearTimeout(w.timer);x.error?w.reject(new Error(x.error)):w.resolve(x.value)});
child.on('error',readyReject);child.on('exit',()=>{readyReject(new Error('owner exited'));for(const w of waiting.values()){clearTimeout(w.timer);w.reject(new Error('owner exited'))}waiting.clear()});
const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;const timer=setTimeout(()=>{waiting.delete(id);reject(new Error('demo timeout'))},10000);waiting.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n')});
let subscription;const deadline=setTimeout(()=>child.kill('SIGKILL'),20000);
try{
 const info=await ready;
 const port={open:r=>rpc('open',r),poll:r=>rpc('poll',r),ack:r=>rpc('ack',r),cursorRead:r=>rpc('cursor',r),cancel:r=>rpc('cancel',r),wait:async()=>{throw new Error('demo finite input exhausted')}};
 subscription=await EventSubscription.connect(port,info.context,{limit:1});
 const before=await subscription.checkpoint();const delivery=await subscription.poll();
 console.log(JSON.stringify({scope:'SYNTHETIC_DEMO_REAL_LOCAL_EVENT_JOURNAL',before:before.position,count:delivery.events[0].payload.count.toString(),receivedNotAcknowledged:(await subscription.checkpoint()).position}));
 const after=await delivery.ack();console.log(JSON.stringify({explicitlyAcknowledged:after.position,replicated:false,exactlyOnce:false}));
 const latest=new LatestSnapshots();latest.publish('1',new Uint8Array([1]));latest.publish('2',new Uint8Array([2]));console.log('latest snapshot revision',String((await latest.next()).value.revision));await latest.return();
}finally{
 if(subscription)await subscription.close().catch(()=>{});
 try{await rpc('quit')}catch{child.kill('SIGKILL')}
 if(child.exitCode===null&&child.signalCode===null)await new Promise(r=>child.once('exit',r));
 clearTimeout(deadline);lines.close();rmSync(data,{recursive:true,force:true});
}
