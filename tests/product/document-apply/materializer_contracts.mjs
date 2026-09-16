import assert from 'node:assert/strict';
import {existsSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const file=new URL('../../../product/wp04/materializer.mjs',import.meta.url);
assert(existsSync(fileURLToPath(file)),'actual-core materialization adapter missing');
const {validateMaterializationRequest}=await import(file);
const p='par-document-apply-local-0035';const a='a'.repeat(64),b='b'.repeat(64),c='c'.repeat(64);
const raw=Buffer.from([0x85,0x6f,0x4a,0x83,0,0,0,0,1,1,0]).toString('base64');
function input(){return {profile:p,schema:'note-v1-local',changes:[{actor:a,sequence:'1',hash:b,dependencies:[],change:raw}],expectedHeads:[b]};}
const cases=[];function test(id,fn){cases.push([id,fn]);}function rejects(name,mutate){test(name,()=>{const q=input();mutate(q);assert.throws(()=>validateMaterializationRequest(q));});}
test('materializer.contract.valid_shape',()=>assert.deepEqual(validateMaterializationRequest(input()),input()));
rejects('materializer.contract.profile',q=>q.profile='other');rejects('materializer.contract.extra',q=>q.extra=true);
rejects('materializer.contract.empty',q=>q.changes=[]);rejects('materializer.contract.duplicate',q=>q.changes.push({...q.changes[0]}));
rejects('materializer.contract.actor_slot',q=>q.changes.push({...q.changes[0],hash:c}));
rejects('materializer.contract.deps_missing',q=>q.changes[0].dependencies=[a]);rejects('materializer.contract.heads_missing',q=>q.expectedHeads=[]);
rejects('materializer.contract.heads_duplicate',q=>q.expectedHeads=[b,b]);rejects('materializer.contract.sequence_boolean',q=>q.changes[0].sequence=true);
rejects('materializer.contract.sequence_numeric',q=>q.changes[0].sequence=1);rejects('materializer.contract.sequence_leading_zero',q=>q.changes[0].sequence='01');
rejects('materializer.contract.actor',q=>q.changes[0].actor='x');rejects('materializer.contract.inner_hash',q=>q.changes[0].hash='x');
rejects('materializer.contract.unknown_descriptor',q=>q.changes[0].extra=true);rejects('materializer.contract.bad_bytes',q=>q.changes[0].change='eA==');
rejects('materializer.contract.compressed',q=>{const r=Buffer.from(raw,'base64');r[8]=2;q.changes[0].change=r.toString('base64');});
rejects('materializer.contract.oversized',q=>q.changes=Array(129).fill(q.changes[0]));
test('materializer.contract.branch_frontier',()=>{const q=input();q.changes.push({actor:c,sequence:'1',hash:a,dependencies:[b],change:raw});q.expectedHeads=[a];assert.deepEqual(validateMaterializationRequest(q),q);});
if(process.argv.includes('--list')){console.log(JSON.stringify(cases.map(x=>x[0]).sort()));process.exit(0);}
const results=[];for(const [id,f] of cases){try{f();results.push({id,status:'PASS'});}catch(e){console.error(id,e);results.push({id,status:'FAIL'});}}
if(process.env.PAR_NODE_RESULT)writeFileSync(process.env.PAR_NODE_RESULT,JSON.stringify({nonce:process.env.HARNESS_NONCE??'standalone',cases:results}));
console.log(JSON.stringify({cases:results.length,result:results.every(x=>x.status==='PASS')?'PASS':'FAIL',realCoreExecuted:false}));process.exitCode=results.every(x=>x.status==='PASS')?0:1;
