/** Protocol-opponent tests; storage/crash behavior is exercised by integration. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const ROOT=process.env.PAR_ROOT||process.cwd(), tests=[];
const test=(id,fn)=>tests.push({id:'event-command.node.'+id,fn});
let lib;
const context=()=>({protocol:'par-local-event-commands-0040',appId:'test.app',spaceId:'11'.repeat(32),streamId:'22'.repeat(32),epoch:'18446744073709551615',schema:{body:'text',count:'uint64'},schemaDigest:'33'.repeat(32),issuer:'44'.repeat(32),journalGeneration:'55'.repeat(32),authority:'owner-publish'});
const op='01'.repeat(16),host='66'.repeat(16);
const input=()=>({operationId:op,payload:{body:{kind:'text',value:'private'},count:{kind:'uint64',value:'18446744073709551615'}},parents:[]});
const result=(ctx=context())=>({context:ctx,hostId:host,operationId:op,kind:'local-committed',sequence:'18446744073709551615',eventId:'77'.repeat(32),replicated:false,cancellationRequested:false});
function setup(fn,ctx=context(),opts={}){
 assert.equal(typeof lib.EventCommands,'function','typed command client is not implemented');
 const calls=[];const port={request:(...args)=>{calls.push(args);return fn(...args)}};
 return {client:new lib.EventCommands(port,ctx,host,opts),calls};
}
const bad=e=>e.code==='COMMAND_INPUT_INVALID';
test('committed-receipt-is-exact-and-local',async()=>{const {client}=setup(async()=>result());const r=await client.publish(input());assert.equal(r.kind,'local-committed');assert.equal(r.sequence,'18446744073709551615');assert.equal(r.replicated,false);assert.ok(Object.isFrozen(r))});
test('abort-before-send-makes-zero-calls',async()=>{const {client,calls}=setup(async()=>result());const ac=new AbortController();ac.abort();const r=await client.publish(input(),{signal:ac.signal});assert.deepEqual(r,{kind:'cancelled',operationId:op,phase:'before-send'});assert.equal(calls.length,0)});
test('abort-after-dispatch-is-unknown-not-rollback',async()=>{const {client,calls}=setup(()=>new Promise(()=>{}));const ac=new AbortController();const p=client.publish(input(),{signal:ac.signal});ac.abort();assert.equal((await p).kind,'outcome-unknown');assert.equal(calls.length,1);assert.equal((await client.publish(input())).kind,'rejected');assert.equal(calls.length,1)});
test('commit-response-racing-abort-is-conservative',async()=>{const ac=new AbortController();const {client}=setup(async()=>{ac.abort();return result()});assert.equal((await client.publish(input(),{signal:ac.signal})).kind,'outcome-unknown')});
test('transport-loss-does-not-trigger-retry',async()=>{const {client,calls}=setup(async()=>{throw new Error('secret untrusted text')});const r=await client.publish(input());assert.equal(r.kind,'outcome-unknown');assert.equal(r.operationId,op);assert.ok(!JSON.stringify(r).includes('secret'));await client.publish(input());assert.equal(calls.length,1)});
test('timeout-bounds-noncooperative-port',async()=>{const {client,calls}=setup(()=>new Promise(()=>{}),context(),{requestTimeoutMs:15});const r=await client.publish(input());assert.equal(r.kind,'outcome-unknown');assert.equal(calls.length,1)});
test('close-during-publish-is-unknown',async()=>{const {client,calls}=setup(()=>new Promise(()=>{}));const p=client.publish(input());client.close();assert.equal((await p).kind,'outcome-unknown');await client.publish(input());assert.equal(calls.length,1)});
test('one-inflight-command-only',async()=>{let finish;const {client,calls}=setup(()=>new Promise(r=>{finish=r}));const p=client.publish(input());const second=await client.inquire(op);assert.equal(second.kind,'rejected');assert.equal(second.code,'COMMAND_BUSY');assert.equal(calls.length,1);finish(result());await p});
test('request-is-snapshotted-before-await',async()=>{let captured,finish;const {client}=setup((method,args)=>{captured=args;return new Promise(r=>{finish=r})});const a=input();const p=client.publish(a);a.payload.body.value='changed';a.parents.push('ab'.repeat(32));assert.equal(captured.payload.body.value,'private');assert.deepEqual(captured.parents,[]);finish(result());await p});
test('number-is-not-canonical-u64',async()=>{const {client,calls}=setup(async()=>result());const a=input();a.payload.count.value=42;await assert.rejects(client.publish(a),bad);assert.equal(calls.length,0)});
test('leading-zero-u64-is-rejected',async()=>{const {client,calls}=setup(async()=>result());const a=input();a.payload.count.value='01';await assert.rejects(client.publish(a),bad);assert.equal(calls.length,0)});
test('overflow-u64-is-rejected',async()=>{const {client}=setup(async()=>result());const a=input();a.payload.count.value='18446744073709551616';await assert.rejects(client.publish(a),bad)});
test('payload-extra-key-rejected',async()=>{const {client}=setup(async()=>result());const a=input();a.payload.extra={kind:'text',value:'x'};await assert.rejects(client.publish(a),bad)});
test('oversize-input-rejected-before-port',async()=>{const {client,calls}=setup(async()=>result());const a=input();a.payload.body.value='x'.repeat(16385);await assert.rejects(client.publish(a),bad);assert.equal(calls.length,0)});
test('accessor-input-not-invoked',async()=>{const {client,calls}=setup(async()=>result());const a=input();let reads=0;Object.defineProperty(a.payload.body,'value',{get(){reads++;return 'x'},enumerable:true});await assert.rejects(client.publish(a),bad);assert.equal(reads,0);assert.equal(calls.length,0)});
test('duplicate-parents-rejected',async()=>{const {client}=setup(async()=>result());const a=input();a.parents=['ab'.repeat(32),'ab'.repeat(32)];await assert.rejects(client.publish(a),bad)});
test('wrong-operation-reply-is-unknown',async()=>{const {client}=setup(async()=>({...result(),operationId:'ab'.repeat(16)}));assert.equal((await client.publish(input())).kind,'outcome-unknown')});
test('wrong-host-reply-is-unknown',async()=>{const {client}=setup(async()=>({...result(),hostId:'ab'.repeat(16)}));assert.equal((await client.publish(input())).kind,'outcome-unknown')});
test('wrong-context-reply-is-unknown',async()=>{const {client}=setup(async()=>result({...context(),streamId:'ab'.repeat(32)}));assert.equal((await client.publish(input())).kind,'outcome-unknown')});
test('replicated-success-claim-is-rejected',async()=>{const {client}=setup(async()=>({...result(),replicated:true}));assert.equal((await client.publish(input())).kind,'outcome-unknown')});
test('numeric-sequence-is-never-coerced',async()=>{const {client}=setup(async()=>({...result(),sequence:42}));assert.equal((await client.publish(input())).kind,'outcome-unknown')});
test('owner-rejection-is-not-unknown',async()=>{const {context:ctx,hostId,operationId}=result();const {client}=setup(async()=>({context:ctx,hostId,operationId,kind:'rejected',code:'NOT_AUTHORIZED'}));assert.deepEqual(await client.publish(input()),{kind:'rejected',operationId:op,code:'NOT_AUTHORIZED'})});
test('owner-cancel-confirmation-is-before-commit',async()=>{const {context:ctx,hostId,operationId}=result();const {client}=setup(async()=>({context:ctx,hostId,operationId,kind:'cancelled',phase:'before-commit'}));assert.equal((await client.publish(input())).phase,'before-commit')});
test('inquiry-notfound-is-never-publish',async()=>{const {context:ctx,hostId,operationId}=result();const {client,calls}=setup(async()=>({context:ctx,hostId,operationId,kind:'not-found-local'}));assert.deepEqual(await client.inquire(op),{kind:'not-found-local',operationId:op});assert.equal(calls[0][0],'inquire');assert.equal(calls.length,1)});
test('inquiry-failure-is-not-absence',async()=>{const {client,calls}=setup(async()=>{throw new Error('disconnect')});const r=await client.inquire(op);assert.equal(r.kind,'rejected');assert.equal(r.code,'INQUIRY_UNAVAILABLE');assert.equal(calls.length,1)});
test('read-only-client-cannot-publish',async()=>{const {client,calls}=setup(async()=>result(),{...context(),authority:'inquire-only'});const r=await client.publish(input());assert.equal(r.code,'COMMAND_NOT_AUTHORIZED');assert.equal(calls.length,0)});
test('signed-integers-and-empty-bytes-retain-wire-types',async()=>{const ctx={...context(),schema:{delta:'int64',data:'bytes',ok:'bool'}};const {client,calls}=setup(async()=>result(ctx),ctx);const a={operationId:op,payload:{delta:{kind:'int64',value:'-9223372036854775808'},data:{kind:'bytes',value:''},ok:{kind:'bool',value:false}},parents:[]};assert.equal((await client.publish(a)).kind,'local-committed');assert.equal(calls[0][1].payload.delta.value,'-9223372036854775808')});
test('returned-receipt-is-not-peer-owned',async()=>{const reply=result();const {client}=setup(async()=>reply);const receipt=await client.publish(input());reply.sequence='2';assert.equal(receipt.sequence,'18446744073709551615')});
test('synchronous-port-throw-has-no-unhandled-rejection',async()=>{const errors=[];const capture=e=>errors.push(e);process.on('unhandledRejection',capture);try{const {client,calls}=setup(()=>{throw new Error('synchronous loss')});assert.equal((await client.publish(input())).kind,'outcome-unknown');await new Promise(r=>setImmediate(r));assert.equal(errors.length,0);assert.equal(calls.length,1)}finally{process.off('unhandledRejection',capture)}});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0)}
lib=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')));
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});console.log('PASS',t.id)}catch(e){cases.push({id:t.id,status:'FAIL'});console.error('FAIL',t.id,e)}}
if(process.env.HARNESS_RESULT_PATH)fs.writeFileSync(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));process.exitCode=cases.every(c=>c.status==='PASS')?0:1;
