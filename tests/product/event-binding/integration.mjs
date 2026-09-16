import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createInterface} from 'node:readline';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
const ROOT=process.env.PAR_ROOT||process.cwd();
const tests=[];const test=(id,fn)=>tests.push({id:'event-binding.integration.'+id,fn});
let EventSubscription;
export async function worker(root){
 const child=spawn(process.env.PAR_PYTHON||'python3',['-I','-S','-B',path.join(ROOT,'tests/product/event-binding/owner_worker.py'),root],{cwd:ROOT,stdio:['pipe','pipe','pipe']});
 let nextId=0,readyResolve,readyReject;const pending=new Map();let stderr='';const ready=new Promise((r,j)=>{readyResolve=r;readyReject=j});
 child.stderr.on('data',b=>{stderr=(stderr+b.toString()).slice(-8192)});
 const reader=createInterface({input:child.stdout});
 reader.on('line',line=>{try{assert.ok(Buffer.byteLength(line)<=1500000);const x=JSON.parse(line);if(x.ready){readyResolve(x);return}const waiter=pending.get(x.id);if(!waiter)return;pending.delete(x.id);clearTimeout(waiter.timer);if(x.error)waiter.reject(Object.assign(new Error(x.error),{code:x.error}));else waiter.resolve(x.value)}catch(e){readyReject(e);for(const w of pending.values()){clearTimeout(w.timer);w.reject(e)}pending.clear()}});
 child.on('error',readyReject);const exited=new Promise(resolve=>child.once('exit',(code,signal)=>{readyReject(new Error('owner exited '+code+' '+signal+' '+stderr));for(const w of pending.values()){clearTimeout(w.timer);w.reject(new Error('owner disconnected'))}pending.clear();resolve({code,signal})}));
 const timer=setTimeout(()=>{child.kill('SIGKILL');readyReject(new Error('owner startup timeout '+stderr))},10000);let info;try{info=await ready}finally{clearTimeout(timer)}
 function rpc(method,params={}){return new Promise((resolve,reject)=>{const id=++nextId;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('owner timeout'))},10000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n',e=>{if(e){clearTimeout(timer);pending.delete(id);reject(e)}})})}
 const port={open:r=>rpc('open',r),poll:r=>rpc('poll',r),ack:r=>rpc('ack',r),cursorRead:r=>rpc('cursor',r),cancel:r=>rpc('cancel',r),wait:s=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(t);reject(new Error('abort'))};const t=setTimeout(()=>{s.removeEventListener('abort',abort);resolve()},50);s.addEventListener('abort',abort,{once:true});if(s.aborted)abort()})};
 async function stop(kill=false){if(child.exitCode===null&&child.signalCode===null){if(kill)child.kill('SIGKILL');else{try{await rpc('quit')}catch{child.kill('SIGKILL')}}}let t;try{await Promise.race([exited,new Promise((_,j)=>{t=setTimeout(()=>{child.kill('SIGKILL');j(new Error('cleanup timeout'))},5000)})])}finally{clearTimeout(t);reader.close();child.stdin.destroy();child.stdout.destroy();child.stderr.destroy()}}
 return {child,info,port,rpc,stop,exited};
}
async function run(fn){const root=mkdtempSync(path.join(tmpdir(),'par-event-sdk-'));const workers=[];const start=async()=>{const w=await worker(root);workers.push(w);return w};try{await fn(start,root)}finally{for(const w of workers)await w.stop();rmSync(root,{recursive:true,force:true})}}
test('real-journal-bigint-and-manual-ack',()=>run(async start=>{const w=await start(),s=await EventSubscription.connect(w.port,w.info.context,{limit:1});const a=await s.next();assert.equal(a.value.events[0].payload.count,18446744073709551615n);assert.equal((await s.checkpoint()).position,'0');await a.value.ack();assert.equal((await s.checkpoint()).position,'1');const b=await s.next();assert.equal(b.value.events[0].sequence,2n);await s.close()}));
test('consumer-break-redelivers-after-process-restart',()=>run(async start=>{let w=await start();const pin=w.info.context;const s=await EventSubscription.connect(w.port,pin,{limit:1});const before=s.lastCursor;let id;for await(const b of s){id=b.events[0].eventId;break}await w.stop();w=await start();assert.deepEqual(w.info.context,pin);const n=await EventSubscription.connect(w.port,pin,{limit:1,expectedCursor:before});assert.equal((await n.next()).value.events[0].eventId,id);await n.close()}));
test('acknowledged-survives-process-restart',()=>run(async start=>{let w=await start();const pin=w.info.context;const s=await EventSubscription.connect(w.port,pin,{limit:1});const c=await (await s.poll()).ack();await s.close();await w.stop();w=await start();const n=await EventSubscription.connect(w.port,pin,{limit:1,expectedCursor:c});assert.equal((await n.poll()).events[0].sequence,2n);await n.close()}));
test('authority-change-rejects-ack',()=>run(async start=>{const w=await start(),s=await EventSubscription.connect(w.port,w.info.context,{limit:1});const b=await s.poll();await w.rpc('test_authority_change');await assert.rejects(b.ack(),e=>e.code==='ACK_OUTCOME_UNKNOWN');await s.close();assert.equal(s.lastCursor.position,'0')}));
test('owner-lost-ack-reconcile-on-reconnect',()=>run(async start=>{let w=await start();const pin=w.info.context;const s=await EventSubscription.connect(w.port,pin,{limit:1});const c=s.lastCursor;const b=await s.poll();await w.rpc('test_ack_loss');await assert.rejects(b.ack(),e=>e.code==='ACK_OUTCOME_UNKNOWN');await s.close().catch(()=>{});await w.stop();w=await start();const n=await EventSubscription.connect(w.port,pin,{limit:1,expectedCursor:c});assert.equal(n.lastCursor.position,'1');assert.equal((await n.poll()).events[0].sequence,2n);await n.close()}));
test('sigkill-before-ack-redelivers',()=>run(async start=>{let w=await start();const pin=w.info.context;const s=await EventSubscription.connect(w.port,pin,{limit:1});const c=s.lastCursor;const b=await s.poll();await w.stop(true);await s.close().catch(()=>{});w=await start();const n=await EventSubscription.connect(w.port,pin,{limit:1,expectedCursor:c});assert.equal((await n.poll()).events[0].eventId,b.events[0].eventId);await n.close()}));
test('sigkill-after-ack-commit-keeps-cursor',()=>run(async start=>{let w=await start();const pin=w.info.context;const s=await EventSubscription.connect(w.port,pin,{limit:1});const c=s.lastCursor,b=await s.poll();await w.rpc('test_ack_kill');await assert.rejects(b.ack(),e=>e.code==='ACK_OUTCOME_UNKNOWN');await w.exited;await s.close().catch(()=>{});w=await start();const n=await EventSubscription.connect(w.port,pin,{limit:1,expectedCursor:c});assert.equal(n.lastCursor.position,'1');await n.close()}));
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0)}
({EventSubscription}=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')).href));
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});console.log('PASS '+t.id)}catch(e){cases.push({id:t.id,status:'FAIL',error:String(e.stack||e)});console.error('FAIL '+t.id+' '+e.stack)}}
if(process.env.HARNESS_RESULT_PATH)fs.writeFileSync(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));
console.log(JSON.stringify({result:cases.every(x=>x.status==='PASS')?'PASS':'FAIL',cases:cases.length}));process.exitCode=cases.every(x=>x.status==='PASS')?0:1;
