import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const ROOT=process.env.PAR_ROOT;
const LIB=process.env.PAR_PRESENTER_BUILD||path.join(ROOT,'product/wp11/lib');
const cases=[];
const test=(id,fn)=>cases.push({id:'application.observation.'+id,fn});
let api,data;
async function setup(which='candidate') {
  api??=await import(pathToFileURL(path.join(LIB,'index.js')));
  assert.equal(typeof api.validateApplicationObservation,'function','application observation binding is not implemented');
  data??=JSON.parse(await fs.readFile(process.env.PAR_APPLICATION_FIXTURE,'utf8'));
  return structuredClone(data[which]);
}
const denied=(fn,code)=>assert.rejects(fn,e=>e.code===code);
const port=f=>({observe:async id=>id===null?f.empty:f.refreshed});
test('empty_is_not_tombstoned',async()=>{const f=await setup();const s=api.projectApplicationObservation(f.empty,f.pin);assert.equal(s.document.read,'absent-local');assert.equal(s.document.knownCatalogComplete,false);});
test('candidate_body_hidden',async()=>{const f=await setup();const s=api.projectApplicationObservation(f.recorded,f.pin);assert.equal(s.document.text,'');assert.equal(s.document.title,'');assert.equal(s.document.applied,false);assert.equal(s.authority.sharedWriteAllowed,false);});
test('application_is_not_commit_receipt',async()=>{const f=await setup();const s=api.projectApplicationObservation(f.recorded,f.pin);assert.equal(s.local.state,'unknown');assert.equal(s.local.operationId,null);assert.equal(s.supportedCommands.includes('inspect-operation'),false);});
test('simulated_positive_contract_is_read_only',async()=>{const f=await setup('simulated');const s=api.projectApplicationObservation(f.recorded,f.pin);assert.ok(s.document.text.startsWith('SYNTHETIC-'));assert.equal(s.document.applied,true);assert.equal(s.authority.sharedWriteAllowed,false);assert.equal(s.protection.observations.length,0);});
test('candidate_notice_not_crdt_success',async()=>{const f=await setup();assert.equal(api.applicationNotice(f.recorded).key,'application.candidate-hidden');});
test('binding_calls_exact_operation_once',async()=>{const f=await setup();const calls=[];const b=new api.ApplicationReadBinding(f.pin,f.empty,{observe:async id=>{calls.push(id);return f.recorded;}});await b.refresh(f.recorded.operation.id);assert.deepEqual(calls,[f.recorded.operation.id]);assert.equal(b.observation.operation.state,'OBSERVED_CANDIDATE');});
test('malformed_operation_no_io',async()=>{const f=await setup();let calls=0;const b=new api.ApplicationReadBinding(f.pin,f.empty,{observe:async()=>{calls++;return f.recorded;}});await denied(()=>b.refresh('bad'),'INVALID_INPUT');assert.equal(calls,0);});
test('close_clears_text_and_stops_future_calls',async()=>{const f=await setup('simulated');let calls=0;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>{calls++;return f.refreshed;}});b.close();assert.equal(b.current.document.text,'');await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_BINDING_CLOSED');assert.equal(calls,0);});
test('refresh_masks_text_while_waiting',async()=>{const f=await setup('simulated');let resolve;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:()=>new Promise(r=>resolve=r)});const p=b.refresh(f.recorded.operation.id);assert.equal(b.current.document.text,'');assert.equal(b.status,'CHECKING');resolve(f.refreshed);await p;assert.ok(b.current.document.text);});
test('error_clears_text_and_does_not_auto_retry',async()=>{const f=await setup('simulated');let calls=0;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>{calls++;throw Error('no authority');}});await assert.rejects(()=>b.refresh(f.recorded.operation.id));assert.equal(b.current.document.text,'');assert.equal(b.current.document.applied,false);assert.equal(b.status,'UNAVAILABLE');assert.equal(calls,1);});
test('close_discards_late_response',async()=>{const f=await setup('simulated');let resolve;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:()=>new Promise(r=>resolve=r)});const p=b.refresh(f.recorded.operation.id);b.close();resolve(f.refreshed);await denied(()=>p,'APPLICATION_BINDING_CLOSED');assert.equal(b.current.document.text,'');});
test('overlapping_request_refused',async()=>{const f=await setup();let resolve;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:()=>new Promise(r=>resolve=r)});const p=b.refresh(f.recorded.operation.id);await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_BINDING_BUSY');resolve(f.refreshed);await p;});
test('different_stream_requires_explicit_binding',async()=>{const f=await setup();f.refreshed.streamId='f'.repeat(32);const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.refreshed});await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_BINDING_MISMATCH');});
test('old_response_refused',async()=>{const f=await setup();const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.empty});await denied(()=>b.refresh(null),'STALE_VIEW');});
test('same_sequence_changed_content_refused',async()=>{const f=await setup();f.refreshed.sequence=f.recorded.sequence;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.refreshed});await denied(()=>b.refresh(f.recorded.operation.id),'REVISION_REUSED');});
test('identical_duplicate_allowed',async()=>{const f=await setup();const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.recorded});await b.refresh(f.recorded.operation.id);assert.equal(b.status,'CURRENT');});
test('wrong_operation_refused',async()=>{const f=await setup();const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.unknown});await denied(()=>b.refresh(f.recorded.operation.id),'OPERATION_MISMATCH');});
test('frontier_regression_refused',async()=>{const f=await setup();f.empty.sequence='99';f.empty.revision='9'.repeat(64);const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.empty});await denied(()=>b.refresh(null),'APPLICATION_FRONTIER_REGRESSED');});
test('same_frontier_different_digest_refused',async()=>{const f=await setup();f.refreshed.application.eventDigest='e'.repeat(64);f.refreshed.operation.eventDigest='e'.repeat(64);const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.refreshed});await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_FRONTIER_CHANGED');});
test('copied_and_frozen_output',async()=>{const f=await setup();const b=new api.ApplicationReadBinding(f.pin,f.recorded,port(f));f.recorded.application.heads=[];assert.ok(b.observation.application.heads.length);assert.throws(()=>{b.current.document.text='x';});});
for(const [name,mutate] of [
 ['plaintext_in_candidate',r=>r.application.note={title:'x',body:'x',titleConflicts:[]}],
 ['applied_in_candidate',r=>r.application.applied=true],['inner_in_candidate',r=>r.application.innerValidated=true],
 ['candidate_core_digest',r=>r.application.recheckedCoreDigest='e'.repeat(64)],
 ['shared_write',r=>r.capabilities.sharedCommit=true],['apply',r=>r.capabilities.apply=true],
 ['replication',r=>r.replicationObserved=true],['global_latest',r=>r.globalLatestProven=true],['product',r=>r.productQualified=true],
 ['catalog',r=>r.catalogComplete=true],['sequence_bool',r=>r.sequence=true],['sequence_overflow',r=>r.sequence='18446744073709551616'],
 ['revision_bool',r=>r.application.revision=true],['operation_future',r=>r.operation.revision=64],['observed_without_id',r=>r.operation.id=null],
 ['observed_without_digest',r=>r.operation.eventDigest=null],['unobserved_with_record',r=>r.operation.state='NOT_OBSERVED'],
 ['duplicate_head',r=>r.application.heads.push(r.application.heads[0])],['extra_field',r=>r.extra='x'],
 ['unknown_phase',r=>r.application.state='APPLIED'],['time',r=>r.observedAt='tomorrow'],['reader_false',r=>r.authority.readerAuthorized=false],
 ['auth_epoch',r=>r.authority.epoch='2'],['core_kind',r=>r.application.evidenceClass='trusted-by-user'],
 ['unsafe_string',r=>r.scope.appId='\ud800']
])test('reject_'+name,async()=>{const f=await setup();mutate(f.recorded);assert.throws(()=>api.validateApplicationObservation(f.recorded));});
for(const key of ['streamId','storeGeneration','certificateDigest','engineDigest'])test('bound_'+key,async()=>{const f=await setup();const p=structuredClone(f.pin);p[key]='f'.repeat(key==='certificateDigest'||key==='engineDigest'?64:32);assert.throws(()=>api.projectApplicationObservation(f.recorded,p));});
test('array_getter_not_executed',async()=>{const f=await setup();let calls=0;Object.defineProperty(f.recorded.application.heads,'0',{get(){calls++;return 'a'.repeat(64);}});assert.throws(()=>api.validateApplicationObservation(f.recorded));assert.equal(calls,0);});
test('array_tojson_not_executed',async()=>{const f=await setup();let calls=0;Object.defineProperty(f.recorded.application.heads,'toJSON',{value(){calls++;return [];}});assert.throws(()=>api.validateApplicationObservation(f.recorded));assert.equal(calls,0);});
test('positive_note_bound_to_engine_pin',async()=>{const f=await setup('simulated');f.recorded.application.recheckedCoreDigest='e'.repeat(64);assert.throws(()=>api.validateApplicationObservation(f.recorded));});
test('positive_note_missing_refused',async()=>{const f=await setup('simulated');f.recorded.application.note=null;assert.throws(()=>api.validateApplicationObservation(f.recorded));});
test('positive_note_unknown_field_refused',async()=>{const f=await setup('simulated');f.recorded.application.note.code='execute';assert.throws(()=>api.validateApplicationObservation(f.recorded));});
test('previously_observed_operation_cannot_disappear',async()=>{const f=await setup();f.refreshed.operation={id:f.recorded.operation.id,state:'NOT_OBSERVED',revision:null,eventDigest:null};const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.refreshed});await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_RESULT_CHANGED');});
test('previously_observed_operation_cannot_change_revision',async()=>{const f=await setup();f.recorded.application.revision=2;f.recorded.operation.revision=1;f.recorded.operation.eventDigest='d'.repeat(64);f.refreshed.application.revision=2;f.refreshed.operation.revision=2;const b=new api.ApplicationReadBinding(f.pin,f.recorded,{observe:async()=>f.refreshed});await denied(()=>b.refresh(f.recorded.operation.id),'APPLICATION_RESULT_CHANGED');});
test('application_notices_have_localized_copy',async()=>{const f=await setup();const m=api.applicationNotice(f.recorded);assert.match(api.formatMessage(m,'ja'),/候補/);assert.match(api.formatMessage(m,'en'),/candidate/i);});
if(process.argv.includes('--list')){console.log(JSON.stringify(cases.map(x=>x.id)));process.exit(0);}
const results=[];for(const c of cases){try{await c.fn();results.push({id:c.id,status:'PASS'});}catch(e){results.push({id:c.id,status:'FAIL'});console.error(c.id,e.stack);}}
if(process.env.HARNESS_RESULT_PATH)await fs.writeFile(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases:results}));
console.log(JSON.stringify({scope:'TYPED_OBSERVATION_CONTRACTS_WITH_EXPLICIT_SIMULATED_CORE',cases:results,result:results.every(x=>x.status==='PASS')?'PASS':'FAIL'}));process.exitCode=results.some(x=>x.status!=='PASS')?1:0;
