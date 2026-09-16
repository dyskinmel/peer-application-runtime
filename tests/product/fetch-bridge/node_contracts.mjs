// Strict typed-owner observation/DOM contracts. Not a real browser or CRDT.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const tests=[];const test=(name,fn)=>tests.push({id:'fetch.bridge.node.'+name,fn});
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const sha=v=>createHash('sha256').update(canonical(v)).digest('hex');
const signed=v=>{delete v.revision;v.revision=sha(v);return v;};
let api;
async function setup(){
 const lib=process.env.PAR_PRESENTER_BUILD||path.join(process.env.PAR_ROOT,'product/wp11/lib');
 assert.ok(existsSync(path.join(lib,'fetch-observation.js')),'fetch observation binding not implemented');
 api??=await import(pathToFileURL(path.join(lib,'fetch-observation.js')));
 const data=JSON.parse(await fs.readFile(process.env.PAR_FETCH_FIXTURE,'utf8'));return structuredClone(data);
}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
test('python_observation_and_digest_accepted',async()=>{const f=await setup();const v=await api.validateFetchObservation(f.waiting,f.pin);assert.equal(v.records[0].state,'WAITING_DEPENDENCIES');});
test('core_blocked_is_not_applied',async()=>{const f=await setup();const v=await api.validateFetchObservation(f.blocked,f.pin);const p=api.presentFetchObservation(v,'en');assert.match(p.message,/core|validation/i);assert.equal(p.applied,false);assert.equal(p.acknowledged,false);});
test('japanese_copy_not_shared_commit',async()=>{const f=await setup();const v=await api.validateFetchObservation(f.waiting,f.pin);const p=api.presentFetchObservation(v,'ja');assert.match(p.message,/依存/);assert.match(p.disclaimer,/共有文書/);});
test('owned_and_frozen',async()=>{const f=await setup();const v=await api.validateFetchObservation(f.waiting,f.pin);f.waiting.records.length=0;assert.equal(v.records.length,1);assert.throws(()=>{v.records[0].state='APPLIED';});});
test('refresh_has_no_implicit_validation',async()=>{const f=await setup();let n=0;const b=new api.FetchReadBinding(f.pin,{observe:async()=>{n++;return f.waiting;}});await b.refresh();assert.equal(n,1);assert.equal(b.current.status,'CURRENT');assert.equal(b.current.observation.applied,false);});
test('new_request_masks_old_panel',async()=>{const f=await setup();let value=Promise.resolve(f.waiting);const b=new api.FetchReadBinding(f.pin,{observe:()=>value});await b.refresh();const d=deferred();value=d.promise;const p=b.refresh();assert.equal(b.current.status,'CHECKING');assert.equal(b.current.observation,null);d.resolve(f.ready);await p;});
test('late_response_cannot_replace_newer',async()=>{const f=await setup();const a=deferred(),c=deferred();let n=0;const b=new api.FetchReadBinding(f.pin,{observe:()=>++n===1?a.promise:c.promise});const old=b.refresh();const fresh=b.refresh();c.resolve(f.ready);await fresh;a.resolve(f.waiting);await assert.rejects(()=>old);assert.equal(b.current.observation.sequence,f.ready.sequence);});
test('close_discards_late',async()=>{const f=await setup();const d=deferred();const b=new api.FetchReadBinding(f.pin,{observe:()=>d.promise});const p=b.refresh();b.close();d.resolve(f.waiting);await assert.rejects(()=>p);assert.equal(b.current.status,'CLOSED');assert.equal(b.current.observation,null);});
test('failure_clears_panel_and_never_retries',async()=>{const f=await setup();let n=0;const b=new api.FetchReadBinding(f.pin,{observe:async()=>{n++;throw Error('private failure detail');}});await assert.rejects(()=>b.refresh());assert.equal(n,1);assert.equal(b.current.status,'UNAVAILABLE');assert.equal(b.current.observation,null);assert.ok(!JSON.stringify(b.current).includes('private failure'));});
test('sequence_replay_rejected',async()=>{const f=await setup();const b=new api.FetchReadBinding(f.pin,{observe:async()=>f.waiting});await b.refresh();await assert.rejects(()=>b.refresh());assert.equal(b.current.observation,null);});
for(const [name,modify] of [
 ['applied',v=>v.applied=true],['inner',v=>v.innerValidated=true],['ack',v=>v.acknowledged=true],['commit',v=>v.localCommitted=true],['replicated',v=>v.replicated=true],['qualified',v=>v.productQualified=true],
 ['extra',v=>v.body='opaque must not become note'],['row_extra',v=>v.records[0].title='injected'],['bad_state',v=>v.records[0].state='APPLIED'],['bool_sequence',v=>v.sequence=true],['sequence_overflow',v=>v.sequence='18446744073709551616'],
 ['duplicate_roots',v=>v.records.push(structuredClone(v.records[0]))],['missing_duplicate',v=>v.records[0].missingInner.push(v.records[0].missingInner[0])],['validation_extra',v=>v.records[0].validation={state:'CORE_BLOCKED',reason:'CORE_UNAVAILABLE',body:'bad'}],
 ['operation_without_id',v=>v.operation.state='OUTCOME_UNKNOWN'],['reason_detail',v=>v.operation.reason='secret: error detail'],
])test('reject_'+name,async()=>{const f=await setup();modify(f.waiting);signed(f.waiting);await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));});
for(const key of ['planDigest','targetDigest','streamId','inboxGeneration','storeGeneration','connectionGeneration'])test('pin_'+key,async()=>{const f=await setup();f.waiting.pin[key]=key==='connectionGeneration'?'10':'f'.repeat(f.waiting.pin[key].length);signed(f.waiting);await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));});
test('scope_control_head_is_bound',async()=>{const f=await setup();f.waiting.pin.scope.controlHead='e'.repeat(64);signed(f.waiting);await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));});
test('digest_tamper_rejected',async()=>{const f=await setup();f.waiting.localRevision='f'.repeat(64);await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));});
test('getter_not_executed',async()=>{const f=await setup();let n=0;Object.defineProperty(f.waiting,'records',{get(){n++;return[];},enumerable:true});await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));assert.equal(n,0);});
test('array_getter_not_executed',async()=>{const f=await setup();let n=0;Object.defineProperty(f.waiting.records,'0',{get(){n++;return{};},enumerable:true});await assert.rejects(()=>api.validateFetchObservation(f.waiting,f.pin));assert.equal(n,0);});
test('unknown_operation_is_not_permission_to_retry',async()=>{const f=await setup();f.waiting.operation={id:'a'.repeat(32),state:'OUTCOME_UNKNOWN',reason:'APPLICATION_OUTCOME_UNKNOWN',revision:null,expectedRevision:0};signed(f.waiting);const v=await api.validateFetchObservation(f.waiting,f.pin);assert.equal(api.presentFetchObservation(v,'ja').automaticRetry,false);});
for(const state of ['INQUIRY_FAILED','NOT_OBSERVED'])test('uncertain_'+state+'_display_requires_inquiry',async()=>{const f=await setup();f.waiting.operation={id:'a'.repeat(32),state,reason:null,revision:null,expectedRevision:0};signed(f.waiting);const v=await api.validateFetchObservation(f.waiting,f.pin);const p=api.presentFetchObservation(v,'ja');assert.match(p.message,/操作ID/);assert.match(p.message,/未確定|不明/);assert.equal(p.automaticRetry,false);});
test('observed_application_record_is_not_unapplied_claim',async()=>{const f=await setup();f.blocked.operation={id:'a'.repeat(32),state:'OBSERVED_APPLICATION_RECORD',reason:null,revision:1,expectedRevision:0};signed(f.blocked);const v=await api.validateFetchObservation(f.blocked,f.pin);const p=api.presentFetchObservation(v,'ja');assert.match(p.message,/記録/);assert.ok(!p.message.includes('未適用'));assert.equal(p.sharedCommit,false);});
test('known_record_cannot_be_overwritten_by_absence',async()=>{const f=await setup();f.waiting.operation={id:'a'.repeat(32),state:'OBSERVED_APPLICATION_RECORD',reason:null,revision:1,expectedRevision:0};signed(f.waiting);let value=f.waiting;const b=new api.FetchReadBinding(f.pin,{observe:async()=>value});await b.refresh();value=structuredClone(f.waiting);value.sequence=String(BigInt(value.sequence)+1n);value.operation.state='NOT_OBSERVED';value.operation.revision=null;signed(value);await assert.rejects(()=>b.refresh());assert.equal(b.current.status,'UNAVAILABLE');});
class Element{constructor(doc,tag){this.ownerDocument=doc;this.tagName=tag;this.children=[];this.attrs={};this._text='';}set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}setAttribute(k,v){this.attrs[k]=v;}append(...v){this.children.push(...v);}replaceChildren(...v){this._text='';this.children=v;}remove(){this.children=[];this._text='';}}
class Document{createElement(t){return new Element(this,t);}}
test('status_renderer_read_only_dom_contract',async()=>{const f=await setup();const b=new api.FetchReadBinding(f.pin,{observe:async()=>f.blocked});const doc=new Document(),root=doc.createElement('div');const renderer=api.mountFetchStatus(root,b,'ja');await renderer.refresh();assert.match(root.textContent,/未適用|適用.*別/);assert.equal(root.children[0].attrs.role,'status');renderer.destroy();assert.equal(root.textContent,'');assert.equal(b.current.status,'CURRENT');});
test('renderer_destroy_ignores_late_result',async()=>{const f=await setup();const d=deferred();const b=new api.FetchReadBinding(f.pin,{observe:()=>d.promise});const doc=new Document(),root=doc.createElement('div');const r=api.mountFetchStatus(root,b,'en');const pending=r.refresh();r.destroy();d.resolve(f.waiting);await pending;assert.equal(root.textContent,'');});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id)));process.exit(0);}
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});}catch(e){cases.push({id:t.id,status:'FAIL'});console.error(t.id,e.stack);}}
if(process.env.HARNESS_RESULT_PATH)await fs.writeFile(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));
console.log(JSON.stringify({result:cases.every(x=>x.status==='PASS')?'PASS':'FAIL',cases,browser_executed:false}));process.exitCode=cases.some(x=>x.status!=='PASS')?1:0;
