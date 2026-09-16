import assert from 'node:assert/strict';import {spawn} from 'node:child_process';import {mkdtempSync,rmSync} from 'node:fs';import fs from 'node:fs';import {tmpdir} from 'node:os';import path from 'node:path';import {createInterface} from 'node:readline';import {pathToFileURL} from 'node:url';
const ROOT=process.env.PAR_ROOT||process.cwd();const tests=[];const test=(id,fn)=>tests.push({id:'event-host.integration.'+id,fn});let lib,Channel;
export async function start(root,mode='existing'){
 if(!lib)lib=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')));
 if(!Channel)Channel=(await import(pathToFileURL(path.join(ROOT,'product/wp10/node/channel.mjs')))).ConnectedEventChannel;
 assert.ok(Channel,'connected private channel not implemented');
 const child=spawn(process.env.PAR_PYTHON||'python3',['-I','-S','-B',path.join(ROOT,'tests/product/event-host/owner_process.py'),root,mode],{cwd:ROOT,stdio:['ignore','pipe','pipe','pipe']});
 let resolve,reject,info,ended,stderr='';const boot=new Promise((a,b)=>{resolve=a;reject=b});
 const reader=createInterface({input:child.stdout});reader.on('line',line=>{try{const r=JSON.parse(line);if(r.ready){info=r;resolve(r)}else if(r.ended)ended=r}catch(e){reject(e)}});
 child.stderr.on('data',b=>stderr=(stderr+b).slice(-8192));child.on('error',reject);
 const exit=new Promise(res=>child.once('exit',(code,signal)=>{reject(new Error('startup exited '+code+' '+signal+' '+stderr));res({code,signal})}));
 let timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('startup timeout '+stderr))},10000);
 try{await boot}finally{clearTimeout(timer)}
 assert.equal(info.socket_family,1);
 const channel=new Channel(child.stdio[3],{expectedContext:info.context,requestTimeoutMs:3000});const hello=await channel.ready;
 const port=new lib.GenerationEventPort(channel,hello.hostId);
 async function stop(kill=false){if(kill&&child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');await channel.close();let timer;try{await Promise.race([exit,new Promise((_,j)=>{timer=setTimeout(()=>{child.kill('SIGKILL');j(new Error('cleanup timeout'))},5000)})])}finally{clearTimeout(timer);reader.close();child.stdout.destroy();child.stderr.destroy();child.stdio[3].destroy()}}
 return {child,port,channel,info,stop,exit,get ended(){return ended}};
}
async function run(fn){const root=mkdtempSync(path.join(tmpdir(),'par-event-host-')),workers=[];const create=async(mode)=>{const w=await start(root,mode);workers.push(w);return w};try{await fn(create,root)}finally{for(const w of workers)await w.stop();rmSync(root,{recursive:true,force:true})}}
test('real-async-notification-not-polling-fixture',()=>run(async create=>{const w=await create('publish-on-wait');const s=await lib.EventSubscription.connect(w.port,w.info.context);assert.equal(await s.poll(),null);const r=await s.next();assert.equal(r.value.events[0].payload.body,'created after wait registered');assert.equal(r.value.events[0].payload.count,18446744073709551615n);assert.equal(s.lastCursor.position,'0');await r.value.ack();assert.equal(s.lastCursor.position,'1');await s.close();await w.stop();assert.equal(w.ended.stats.channels,0);assert.equal(w.ended.stats.waiters,0);assert.ok(w.ended.storage_threads.every(t=>t===w.info.owner_thread))}));
test('unacked-reconnect-redelivers-after-sigkill',()=>run(async create=>{let w=await create();const s=await lib.EventSubscription.connect(w.port,w.info.context);const b=await s.poll(),pin=s.lastCursor;await w.stop(true);w=await create();const again=await lib.EventSubscription.connect(w.port,w.info.context,{expectedCursor:pin});assert.deepEqual((await again.poll()).events,b.events);await again.close()}));
test('ack-commit-response-loss-is-unknown',()=>run(async create=>{let w=await create('ack-kill');const s=await lib.EventSubscription.connect(w.port,w.info.context);const b=await s.poll(),pin=s.lastCursor;await assert.rejects(b.ack(),e=>e.code==='ACK_OUTCOME_UNKNOWN');await w.stop();w=await create('existing');const again=await lib.EventSubscription.connect(w.port,w.info.context,{expectedCursor:pin});assert.equal(again.lastCursor.position,'1');assert.equal(await again.poll(),null);await again.close()}));
test('abort-wait-releases-owner-session',()=>run(async create=>{const w=await create('empty');const s=await lib.EventSubscription.connect(w.port,w.info.context);const p=s.next();await new Promise(r=>setTimeout(r,30));await s.close();assert.equal((await p).done,true);await w.stop();assert.equal(w.ended.stats.waiters,0);assert.equal(w.ended.stats.requests,0)}));
test('loop-break-does-not-ack',()=>run(async create=>{let w=await create();const s=await lib.EventSubscription.connect(w.port,w.info.context);for await(const b of s){assert.equal(b.events.length,1);break}await w.stop();w=await create();const r=await lib.EventSubscription.connect(w.port,w.info.context);assert.equal(r.lastCursor.position,'0');await r.close()}));
test('authority-change-observed-before-ack',()=>run(async create=>{const w=await create('revoke-before-ack');const s=await lib.EventSubscription.connect(w.port,w.info.context);const b=await s.poll();await assert.rejects(b.ack(),e=>e.code==='ACK_OUTCOME_UNKNOWN');assert.equal(s.lastCursor.position,'0');await s.close();await w.stop();assert.equal(w.ended.stats.channels,0)}));
if(process.argv[1] && path.resolve(process.argv[1]) === new URL(import.meta.url).pathname){
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0)}
lib=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')));
try{Channel=(await import(pathToFileURL(path.join(ROOT,'product/wp10/node/channel.mjs')))).ConnectedEventChannel}catch{}
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});console.log('PASS',t.id)}catch(e){cases.push({id:t.id,status:'FAIL'});console.error('FAIL',t.id,e)}}
if(process.env.HARNESS_RESULT_PATH)fs.writeFileSync(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));process.exitCode=cases.every(x=>x.status==='PASS')?0:1;

}
