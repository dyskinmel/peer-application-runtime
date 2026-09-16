import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const R=path.resolve(import.meta.dirname,'../../..');
const tests=[];const test=(id,fn)=>tests.push([`native-provider.node.${id}`,fn]);
const descriptor=JSON.parse(fs.readFileSync(path.join(R,'product/wp14/native-provider-profile.json'),'utf8')).experimentalLocal;
const modulePath=path.join(R,'product/wp14/node/provider-lifetime.mjs');
const load=async()=>import(pathToFileURL(modulePath));

test('descriptor-roundtrip',async()=>{const m=await load();assert.deepEqual(m.validateDescriptor(descriptor),descriptor);});
test('unknown-descriptor-field-rejected',async()=>{const m=await load();await assert.rejects(async()=>m.validateDescriptor({...descriptor,trust:true}),/MANIFEST_FIELDS/);});
test('default-write-operations-not-exposed',async()=>{const m=await load();const p={epoch:()=>descriptor.epoch,observe:async()=>({sequence:1}),inquire:async()=>({operationId:'aa'}),close:async()=>{}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);assert.equal('dispatch'in s,false);assert.equal('save'in s,false);});
test('precancelled-observe-does-not-call-port',async()=>{const m=await load();let calls=0;const c=new AbortController();c.abort();const p={epoch:()=>descriptor.epoch,observe:async()=>{calls++;return{};},inquire:async()=>({}),close:async()=>{}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);await assert.rejects(s.observe(c.signal),/CANCELLED/);assert.equal(calls,0);});
test('stale-epoch-after-observe-rejected',async()=>{const m=await load();let epoch=descriptor.epoch,release;const gate=new Promise(r=>release=r);const p={epoch:()=>epoch,observe:async()=>{await gate;return{sequence:1};},inquire:async()=>({}),close:async()=>{}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);const run=s.observe();epoch='22'.repeat(16);release();await assert.rejects(run,/PROVIDER_EPOCH_CHANGED/);});
test('inquire-operation-id-is-copied-before-await',async()=>{const m=await load();let seen;const p={epoch:()=>descriptor.epoch,observe:async()=>({}),inquire:async id=>{seen=id;return{operationId:id};},close:async()=>{}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);const id='ab'.repeat(16);const r=await s.inquire(id);assert.equal(seen,id);assert.equal(r.operationId,id);});
test('wrong-inquiry-id-rejected',async()=>{const m=await load();const p={epoch:()=>descriptor.epoch,observe:async()=>({}),inquire:async()=>({operationId:'cd'.repeat(16)}),close:async()=>{}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);await assert.rejects(s.inquire('ab'.repeat(16)),/OPERATION_ID_MISMATCH/);});
test('close-is-one-shot',async()=>{const m=await load();let n=0;const p={epoch:()=>descriptor.epoch,observe:async()=>({}),inquire:async()=>({}),close:async()=>{n++;}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);assert.equal(await s.close(),true);assert.equal(await s.close(),true);assert.equal(n,1);});
test('close-failure-is-retained-not-retried',async()=>{const m=await load();let n=0;const p={epoch:()=>descriptor.epoch,observe:async()=>({}),inquire:async()=>({}),close:async()=>{n++;throw new Error('busy');}};const s=new m.ProviderLifetime(descriptor,p,descriptor.epoch);assert.equal(await s.close(),false);assert.equal(await s.close(),false);assert.equal(n,1);assert.equal(s.status().cleanupConfirmed,false);});
test('shared-fixture-defaults-readonly',async()=>{const f=JSON.parse(fs.readFileSync(path.join(R,'product/wp14/provider-lifetime-fixture.json'),'utf8'));assert.deepEqual(f.defaultAllowed,['observe','inquire','close']);assert.equal(f.nativeBuild,'BUILD_NOT_RUN');assert.equal(f.productQualified,false);});

if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(([id])=>id)));process.exit(0);}
const cases=[];for(const[id,fn]of tests){try{await fn();cases.push({id,status:'PASS'});}catch(e){console.error(id+' '+e.stack);cases.push({id,status:'FAIL'});}}
console.log(JSON.stringify({cases,nativeBuildExecuted:false,deviceVerified:false,productQualified:false}));if(cases.some(c=>c.status!=='PASS'))process.exitCode=1;
