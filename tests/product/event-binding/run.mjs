import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const ROOT=process.env.PAR_ROOT||process.cwd();
const tests=[];const test=(id,fn)=>tests.push({id:'event-binding.'+id,fn});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(r=>setTimeout(r,0));
const copy=x=>structuredClone(x);
const context={protocol:'par-sdk-events-local-0038',appId:'test.app',spaceId:'11'.repeat(32),streamId:'22'.repeat(32),epoch:'1',schema:{body:'text',count:'uint64'},schemaDigest:'33'.repeat(32),issuer:'44'.repeat(32),consumerId:'55'.repeat(16),journalGeneration:'66'.repeat(32)};
const session='77'.repeat(16);const zero={position:'0',revision:'0',eventId:null,token:'aa'};
const event=(n=1)=>({sequence:String(n),eventId:n.toString(16).padStart(64,'0'),operationId:n.toString(16).padStart(32,'0'),parents:[],payload:{body:{kind:'text',value:'private'},count:{kind:'uint64',value:'18446744073709551615'}},payloadBytes:64});
function fake(){
 const p={calls:[],cursor:copy(zero),events:[event()],ackError:null};
 const base=kind=>({kind,context:copy(context),sessionId:session});
 p.open=async req=>{p.calls.push('open');return {...base('opened'),cursor:copy(p.cursor)}};
 p.poll=async req=>{p.calls.push('poll');return {...base('batch'),cursor:copy(p.cursor),events:copy(p.events),ackToken:p.events.length?'bb':null,hasMore:false}};
 p.ack=async req=>{p.calls.push('ack');const e=p.events.at(-1);p.cursor={position:e.sequence,revision:String(BigInt(p.cursor.revision)+1n),eventId:e.eventId,token:(200+Number(p.cursor.revision)).toString(16)};p.events=[];if(p.ackError)throw p.ackError;return {...base('acked'),cursor:copy(p.cursor)}};
 p.cursorRead=async req=>({...base('cursor'),cursor:copy(p.cursor)});
 p.cancel=async req=>{p.calls.push('cancel');return {...base('cancelled')}};
 p.wait=signal=>new Promise((resolve,reject)=>{p.calls.push('wait');signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true})});
 return p;
}
let m;async function connected(p=fake(),opts={}){assert.ok(m,'SDK module is not implemented');return {s:await m.EventSubscription.connect(p,context,opts),p}}
const rejects=(promise,code)=>assert.rejects(promise,e=>e.code===code);

test('explicit-ack',async()=>{const {s,p}=await connected();const b=await s.poll();assert.equal(b.events[0].payload.count,18446744073709551615n);assert.equal(p.cursor.position,'0');await b.ack();assert.equal(p.cursor.position,'1');await s.close()});
test('iterator-requires-ack',async()=>{const {s,p}=await connected();assert.equal(s[Symbol.asyncIterator](),s);const r=await s.next();assert.equal(r.done,false);await rejects(s.next(),'ACK_REQUIRED');assert.equal(p.calls.filter(x=>x==='ack').length,0);await r.value.ack();await s.close()});
test('poll-redelivery-no-ack',async()=>{const {s,p}=await connected();const a=await s.poll(),b=await s.poll();assert.deepEqual(a.events,b.events);assert.equal(p.calls.filter(x=>x==='poll').length,2);await s.close();assert.equal(p.cursor.position,'0')});
test('break-never-acks',async()=>{const {s,p}=await connected();for await(const b of s){assert.equal(b.events.length,1);break}assert.equal(p.cursor.position,'0');assert.ok(p.calls.includes('cancel'));assert.equal(s.state,'CLOSED')});
test('consumer-throw-never-acks',async()=>{const {s,p}=await connected();await assert.rejects(async()=>{for await(const b of s){throw new Error('consumer')}});assert.equal(p.cursor.position,'0');assert.equal(s.state,'CLOSED')});
test('concurrent-poll-rejected',async()=>{const p=fake(),d=deferred();const orig=p.poll;p.poll=()=>d.promise;const {s}=await connected(p);const first=s.poll();await rejects(s.poll(),'BUSY');d.resolve(await orig({}));await first;await s.close()});
test('concurrent-ack-rejected',async()=>{const {s,p}=await connected();const b=await s.poll(),d=deferred(),orig=p.ack;p.ack=()=>d.promise;const one=b.ack();await rejects(b.ack(),'BUSY');d.resolve(await orig({}));await one;await s.close()});
test('ack-once-per-delivery',async()=>{const {s,p}=await connected();const b=await s.poll();await b.ack();await b.ack();assert.equal(p.calls.filter(x=>x==='ack').length,1);await s.close()});
test('old-delivery-rejected',async()=>{const {s,p}=await connected();const a=await s.poll();await a.ack();p.events=[event(2)];const b=await s.poll();await rejects(a.ack(),'STALE_DELIVERY');await b.ack();await s.close()});
test('lost-ack-is-unknown',async()=>{const {s,p}=await connected();const b=await s.poll();p.ackError=new Error('secret SQL');await rejects(b.ack(),'ACK_OUTCOME_UNKNOWN');assert.equal(s.state,'ACK_OUTCOME_UNKNOWN');assert.equal(p.cursor.position,'1');await rejects(s.poll(),'RECONNECT_REQUIRED');assert.equal(p.calls.filter(x=>x==='ack').length,1);await s.close()});
test('bad-ack-is-unknown',async()=>{const {s,p}=await connected();const b=await s.poll();p.ack=async()=>({kind:'acked'});await rejects(b.ack(),'ACK_OUTCOME_UNKNOWN');await s.close()});
test('abort-late-poll-discarded',async()=>{const p=fake(),d=deferred(),orig=p.poll,ac=new AbortController();p.poll=()=>d.promise;const {s}=await connected(p,{signal:ac.signal});const result=s.poll();ac.abort();await rejects(result,'CANCELLED');d.resolve(await orig({}));await tick();assert.equal(s.state,'CLOSED');assert.equal(p.cursor.position,'0')});
test('abort-ack-is-unknown',async()=>{const {s,p}=await connected();const b=await s.poll(),d=deferred(),orig=p.ack;p.ack=()=>d.promise;const result=b.ack();await s.close();await rejects(result,'ACK_OUTCOME_UNKNOWN');d.resolve(await orig({}));await tick();assert.equal(s.lastCursor.position,'0')});
test('abort-before-open',async()=>{const p=fake(),ac=new AbortController();ac.abort();await rejects(m.EventSubscription.connect(p,context,{signal:ac.signal}),'CANCELLED');assert.deepEqual(p.calls,[])});
test('late-open-cleanup',async()=>{const p=fake(),d=deferred(),orig=p.open,ac=new AbortController();p.open=()=>d.promise;const q=m.EventSubscription.connect(p,context,{signal:ac.signal});await tick();ac.abort();await rejects(q,'CANCELLED');d.resolve(await orig({}));await tick();assert.ok(p.calls.includes('cancel'))});
test('empty-poll-is-not-end',async()=>{const p=fake();p.events=[];const {s}=await connected(p);assert.equal(await s.poll(),null);assert.equal(s.state,'OPEN');await s.close()});
test('iterator-waits-not-spin',async()=>{const p=fake();p.events=[];const {s}=await connected(p);const q=s.next();await tick();assert.deepEqual(p.calls,['open','poll','wait']);await s.return();const r=await q;assert.equal(r.done,true);assert.equal(p.calls.filter(x=>x==='poll').length,1)});
test('iterator-wakeup',async()=>{const p=fake();p.events=[];const d=deferred();p.wait=()=>d.promise;const {s}=await connected(p);const q=s.next();await tick();p.events=[event()];d.resolve();const r=await q;assert.equal(r.value.events.length,1);await s.close()});
test('prefetch-is-absent',async()=>{const {s,p}=await connected();await s.next();await tick();assert.equal(p.calls.filter(x=>x==='poll').length,1);await s.close()});
test('cancel-failure-is-not-success',async()=>{const {s,p}=await connected();p.cancel=async()=>{throw new Error('no response')};await rejects(s.close(),'CANCEL_OUTCOME_UNKNOWN');assert.equal(s.state,'CLOSED');await rejects(s.close(),'CANCEL_OUTCOME_UNKNOWN')});
test('bounded-cleanup',async()=>{const {s,p}=await connected(undefined,{cleanupTimeoutMs:20});p.cancel=()=>new Promise(()=>{});await rejects(s.close(),'CANCEL_OUTCOME_UNKNOWN');assert.equal(s.state,'CLOSED')});
test('checkpoint-copy',async()=>{const {s}=await connected();const c=s.lastCursor;assert.throws(()=>{c.position='9'});assert.equal(s.lastCursor.position,'0');await s.close()});
test('payload-immutable',async()=>{const {s}=await connected();const b=await s.poll();assert.throws(()=>{b.events[0].payload.body='changed'});assert.throws(()=>{b.events.push(event(2))});await b.ack();await s.close()});
for(const [name,mutate] of [
 ['number-u64',r=>{r.events[0].payload.count.value=9007199254740992}],
 ['leading-zero',r=>{r.events[0].sequence='01'}],
 ['overflow',r=>{r.events[0].payload.count.value='18446744073709551616'}],
 ['negative-u64',r=>{r.events[0].payload.count.value='-1'}],
 ['unknown-field',r=>{r.extra=1}],
 ['context-drift',r=>{r.context.epoch='2'}],
 ['session-drift',r=>{r.sessionId='ab'.repeat(16)}],
 ['cursor-drift',r=>{r.cursor.position='1'}],
 ['gap-sequence',r=>{r.events[0].sequence='2'}],
 ['duplicate-events',r=>{r.events.push(copy(r.events[0]))}],
 ['empty-has-token',r=>{r.events=[]}],
 ['wrong-schema-tag',r=>{r.events[0].payload.count.kind='text'}],
 ['oversize-text',r=>{r.events[0].payload.body.value='x'.repeat(16385)}],
 ['missing-token',r=>{r.ackToken=null}],
 ['wrong-parent',r=>{r.events[0].parents=[r.events[0].eventId]}],
 ['nonboolean-more',r=>{r.hasMore=1}],
 ['wrong-size-type',r=>{r.events[0].payloadBytes=true}],
 ['noncanonical-hex',r=>{r.events[0].eventId='FF'.repeat(32)}]
])test('reject-'+name,async()=>{const p=fake(),orig=p.poll;p.poll=async r=>{const o=await orig(r);mutate(o);return o};const {s}=await connected(p);await rejects(s.poll(),'PORT_INVALID');assert.equal(p.cursor.position,'0');await s.close()});
test('getter-not-evaluated',async()=>{const p=fake(),orig=p.poll;let calls=0;p.poll=async r=>{const o=await orig(r);Object.defineProperty(o,'evil',{get(){calls++;return 1},enumerable:true});return o};const {s}=await connected(p);await rejects(s.poll(),'PORT_INVALID');assert.equal(calls,0);await s.close()});
test('same-cursor-other-token',async()=>{const {s,p}=await connected();p.cursorRead=async()=>({kind:'cursor',context,sessionId:session,cursor:{...zero,token:'bb'}});await rejects(s.checkpoint(),'PORT_INVALID');await s.close()});
test('pin-mismatch',async()=>{const p=fake();await rejects(m.EventSubscription.connect(p,context,{expectedCursor:{position:'1',revision:'1',eventId:event().eventId,token:'cc'}}),'CURSOR_ROLLBACK')});
test('wrong-journal-on-open',async()=>{const p=fake(),orig=p.open;p.open=async r=>{const o=await orig(r);o.context.journalGeneration='ab'.repeat(32);return o};await rejects(m.EventSubscription.connect(p,context),'PORT_INVALID')});
test('bigint-position-exact',async()=>{const p=fake();p.cursor={position:'9007199254740993',revision:'9007199254740993',eventId:event(1).eventId,token:'aa'};p.events=[{...event(2),sequence:'9007199254740994'}];const {s}=await connected(p);const b=await s.poll();assert.equal(b.events[0].sequence,9007199254740994n);await b.ack();assert.equal(s.lastCursor.position,'9007199254740994');await s.close()});
test('snapshot-latest-only',async()=>{const s=new m.LatestSnapshots();s.publish('1',new Uint8Array([1]));s.publish('2',new Uint8Array([2]));const r=await s.next();assert.equal(r.value.revision,2n);assert.deepEqual([...r.value.payload],[2]);await s.return()});
test('snapshot-same-revision-conflict',async()=>{const s=new m.LatestSnapshots();s.publish('1',new Uint8Array([1]));assert.throws(()=>s.publish('1',new Uint8Array([2])),e=>e.code==='REVISION_CONFLICT');await s.return()});
test('snapshot-rollback',async()=>{const s=new m.LatestSnapshots();s.publish('2',new Uint8Array([1]));assert.throws(()=>s.publish('1',new Uint8Array([1])),e=>e.code==='REVISION_ROLLBACK');await s.return()});
test('snapshot-copy-boundary',async()=>{const s=new m.LatestSnapshots(),bytes=new Uint8Array([1]);s.publish('1',bytes);bytes[0]=8;const r=await s.next();assert.equal(r.value.payload[0],1);r.value.payload[0]=3;s.publish('1',new Uint8Array([1]));await s.return()});
test('snapshot-close-wakes',async()=>{const s=new m.LatestSnapshots();const q=s.next();await s.return();assert.equal((await q).done,true);assert.throws(()=>s.publish('1',new Uint8Array()),e=>e.code==='CLOSED')});
test('snapshot-one-waiter',async()=>{const s=new m.LatestSnapshots(),q=s.next();await rejects(s.next(),'BUSY');await s.return();await q});
test('snapshot-bound',async()=>{const s=new m.LatestSnapshots({maxBytes:2});assert.throws(()=>s.publish('1',new Uint8Array(3)),e=>e.code==='RESOURCE_LIMIT');await s.return()});

test('cancel-between-promise-and-publication',async()=>{const {s,p}=await connected();const orig=p.poll;p.poll=r=>{const q=orig(r);q.then(()=>queueMicrotask(()=>{void s.close()}));return q};await rejects(s.poll(),'CANCELLED');assert.equal(s.state,'CLOSED')});
test('cancel-between-ack-and-local-cursor',async()=>{const {s,p}=await connected();const b=await s.poll(),orig=p.ack;p.ack=r=>{const q=orig(r);q.then(()=>queueMicrotask(()=>{void s.close()}));return q};await rejects(b.ack(),'ACK_OUTCOME_UNKNOWN');assert.equal(s.lastCursor.position,'0')});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0)}
try{m=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')).href)}catch(e){console.error('SDK load:',e.code||e.message)}
const cases=[];
for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});console.log('PASS '+t.id)}catch(e){cases.push({id:t.id,status:'FAIL',error:String(e.stack||e)});console.error('FAIL '+t.id+' '+e.stack)}}
const output={schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases};
if(process.env.HARNESS_RESULT_PATH)fs.writeFileSync(process.env.HARNESS_RESULT_PATH,JSON.stringify(output));
console.log(JSON.stringify({result:cases.every(c=>c.status==='PASS')?'PASS':'FAIL',cases:cases.length}));process.exitCode=cases.every(c=>c.status==='PASS')?0:1;
