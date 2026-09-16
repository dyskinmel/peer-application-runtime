import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const tests=[];const test=(id,fn)=>tests.push([`soak.providers.${id}`,fn]);
let runner;const original={profile:'par-caller-application-0052',ownerKey:'a'.repeat(64),operationId:'6f'.repeat(16),expectedRevision:0,targets:['b'.repeat(64)]};
async function directory(f){const root=fs.mkdtempSync(path.join(os.tmpdir(),'par-provider-'));fs.chmodSync(root,0o700);try{return await f(root);}finally{fs.rmSync(root,{recursive:true});}}
const loaded=async()=>{const m=await import('../../../product/wp13/node/provider-contracts.mjs');assert.equal(typeof m.callerConformance,'function','caller provider conformance missing');return m.callerConformance;};
test('local_caller_roundtrip',async()=>directory(async root=>{const {LocalCallerIntent}=await import('../../../product/wp11/node/caller-intent.mjs');const r=await(await loaded())(()=>new LocalCallerIntent(root),original);assert.equal(r.result,'PASS');assert.equal(r.osProtectionProven,false);assert.equal(r.checks.length,7);}));
test('missing_provider_blocked',async()=>{const r=await(await loaded())(null,original);assert.equal(r.result,'BLOCKED');assert.deepEqual(r.checks,[]);});
test('save_ack_without_data_detected',async()=>{await assert.rejects(()=>(runner)(()=>({load:async()=>null,save:async()=>{},markDispatch:async()=>{}}),original),/READBACK/);});
test('volatile_provider_reopen_detected',async()=>{await assert.rejects(()=>(runner)(()=>{let value=null;return{load:async()=>value,save:async original=>{value={original,dispatchAttempted:false};},markDispatch:async()=>{}};},original),/REOPEN/);});
test('marker_ack_without_data_detected',async()=>directory(async root=>{const {LocalCallerIntent}=await import('../../../product/wp11/node/caller-intent.mjs');await assert.rejects(()=>(runner)(()=>{const p=new LocalCallerIntent(root);p.markDispatch=async()=>{};return p;},original),/MARKER/);}));
test('provider_offline_not_expected_rejection',async()=>{await assert.rejects(()=>(runner)(()=>({load:async()=>{throw new Error('PROVIDER_OFFLINE');},save:async()=>{},markDispatch:async()=>{}}),original),/PROVIDER_OFFLINE/);});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(([id])=>id)));process.exit(0);}
const cases=[];try{runner=await loaded();}catch{runner=async()=>{throw new Error('caller provider conformance missing');};}
for(const[id,fn]of tests){try{await fn();cases.push({id,status:'PASS'});}catch(e){console.error(id+' '+e.stack);cases.push({id,status:'FAIL'});}}
console.log(JSON.stringify({cases,osProtectionProven:false}));if(cases.some(c=>c.status!=='PASS'))process.exitCode=1;
