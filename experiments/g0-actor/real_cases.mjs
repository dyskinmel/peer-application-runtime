#!/usr/bin/env node
/** REAL-ONLY probe. Absent core exits 78; there is no substitute engine. */
import assert from 'node:assert/strict';
import {loadPinnedCore,verifyManifest,makeWithCore,validateWithCore,metadata,CoreError,PROFILE} from '../../product/wp04/automerge.mjs';
const specs=['release_js_wasm_identity','generate_single_change','unicode_splice_author_sequence','two_offline_authors','merge_both_arrival_orders','title_register_conflicts','store_replayable_bytes','declared_actor_rejected','declared_hash_rejected','declared_dependencies_rejected','duplicate_change_rejected','missing_dependency_rejected','multiple_chunks_rejected','document_container_rejected'];
if(process.argv.includes('--list')){console.log(JSON.stringify(specs.map(x=>'automerge.real.'+x)));process.exit(0);}
const cases=[];let core;
try{const manifest=process.argv[2];if(!manifest)throw new CoreError('CORE_UNAVAILABLE');core=await loadPinnedCore(manifest);
const A=core.A;const run=(id,fn)=>{fn();cases.push({id:'automerge.real.'+id,status:'PASS'});};
const report=(candidate,closure)=>validateWithCore(core,{profile:PROFILE,schema:'note-v1-local',candidate,closure});
const rejects=(fn)=>assert.throws(fn);const copy=x=>structuredClone(x);let initial,left,right,seq2;
run('release_js_wasm_identity',()=>{assert.equal(core.release.js.version,'3.4.1');assert.equal(core.release.js.gitHead,core.release.wasm.gitHead);});
run('generate_single_change',()=>{initial=makeWithCore(core,{kind:'create',actor:'a'.repeat(64),closure:[],expectedHeads:[],title:'共有',body:'あ😀e\u0301Z'});assert.equal(initial.sequence,'1');assert.equal(report(initial,[]).note.body,'あ😀e\u0301Z');});
run('unicode_splice_author_sequence',()=>{seq2=makeWithCore(core,{kind:'splice',actor:initial.actor,closure:[initial],expectedHeads:[initial.hash],index:1,deleteCount:1,text:'🌸'});assert.equal(seq2.sequence,'2');assert.equal(seq2.actor,initial.actor);assert.equal(report(seq2,[initial]).note.body,'あ🌸e\u0301Z');});
run('two_offline_authors',()=>{left=makeWithCore(core,{kind:'splice',actor:'b'.repeat(64),closure:[initial],expectedHeads:[initial.hash],index:0,deleteCount:0,text:'L'});right=makeWithCore(core,{kind:'splice',actor:'c'.repeat(64),closure:[initial],expectedHeads:[initial.hash],index:0,deleteCount:0,text:'R'});assert.equal(left.sequence,'1');assert.equal(right.sequence,'1');});
run('merge_both_arrival_orders',()=>{const a=report(right,[initial,left]),b=report(left,[initial,right]);assert.deepEqual(a.note,b.note);assert.equal(a.note.body.includes('L'),true);assert.equal(a.note.body.includes('R'),true);});
run('title_register_conflicts',()=>{
 let base=A.init({actor:'d'.repeat(64)}),x,y;
 try{[base]=A.applyChanges(base,[Buffer.from(initial.change,'base64')]);x=A.clone(base,{actor:'e'.repeat(64)});y=A.clone(base,{actor:'f'.repeat(64)});
 x=A.change(x,{time:0},d=>{d.title=new A.ImmutableString('左');});y=A.change(y,{time:0},d=>{d.title=new A.ImmutableString('右');});
 const desc=d=>({...metadata(A.getChangesMetaSince(d,[initial.hash])[0]),change:Buffer.from(A.getLastLocalChange(d)).toString('base64')});
 const out=report(desc(y),[initial,desc(x)]);assert.deepEqual(out.note.titleConflicts,['右','左'].sort());
 }finally{if(x)A.free(x);if(y)A.free(y);A.free(base);}
});
run('store_replayable_bytes',()=>{const replay=report(seq2,[initial]);assert.equal(replay.changes[0].hash,seq2.hash);assert.equal(replay.appliedHashes.length,2);});
run('declared_actor_rejected',()=>rejects(()=>report({...initial,actor:'f'.repeat(64)},[])));
run('declared_hash_rejected',()=>rejects(()=>report({...initial,hash:'f'.repeat(64)},[])));
run('declared_dependencies_rejected',()=>rejects(()=>report({...seq2,dependencies:[]},[initial])));
run('duplicate_change_rejected',()=>rejects(()=>report(initial,[initial])));
run('missing_dependency_rejected',()=>rejects(()=>report(left,[])));
run('multiple_chunks_rejected',()=>rejects(()=>report({...initial,change:Buffer.concat([Buffer.from(initial.change,'base64'),Buffer.from(initial.change,'base64')]).toString('base64')},[])));
run('document_container_rejected',()=>{const d=A.from({title:new A.ImmutableString('x'),body:'x'});try{rejects(()=>report({...initial,change:Buffer.from(A.save(d)).toString('base64')},[]));}finally{A.free(d);}});
verifyManifest(manifest);assert.equal(cases.length,specs.length);console.log(JSON.stringify({result:'PASS',scope:'PINNED_AUTOMERGE_LOCAL_ONLY',engine:core.identity,release:core.release,cases},null,2));
}catch(e){const blocked=e.code==='CORE_UNAVAILABLE';console.log(JSON.stringify({result:blocked?'BLOCKED':'FAIL',code:e.code??e.name,scope:'REAL_CORE_PROBE_NOT_PRODUCT_QUALIFICATION',cases,remaining:specs.length-cases.length},null,2));process.exitCode=blocked?78:1;}
