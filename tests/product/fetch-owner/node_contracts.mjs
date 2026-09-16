import assert from 'node:assert/strict';
import fs from 'node:fs/promises';import {existsSync} from 'node:fs';
import path from 'node:path';import {pathToFileURL} from 'node:url';
const tests=[];const test=(name,fn)=>tests.push({id:'fetch.owner.node.'+name,fn});
let api;
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
async function setup(){
 const lib=process.env.PAR_PRESENTER_BUILD||path.join(process.env.PAR_ROOT,'product/wp11/lib');
 assert.ok(existsSync(path.join(lib,'fetch-owner.js')),'typed fetch owner missing');
 api??=await import(pathToFileURL(path.join(lib,'fetch-owner.js')));
 return JSON.parse(await fs.readFile(process.env.PAR_OWNER_FIXTURE,'utf8'));
}
const mapped=f=>({observe:f.waiting,propose:f.proposed,accept:f.accepted,fetch:f.fetched,validate:f.validated});
function client(f,handler){const calls=[];const port={request:async(op,args,signal)=>{calls.push({op,args,signal});return handler?handler(op,args,signal):structuredClone(mapped(f)[op]);},close:async()=>{}};return{c:new api.FetchOwnerClient(f.pin,port),calls,port};}
test('explicit_observe_uses_python_binding',async()=>{const f=await setup(),{c,calls}=client(f);assert.equal(calls.length,0);await c.observe();assert.equal(c.current.status,'CURRENT');assert.equal(c.current.snapshot.observation.records[0].state,'WAITING_DEPENDENCIES');assert.equal(calls[0].op,'observe');});
test('explicit_flow_no_apply_or_ack',async()=>{const f=await setup(),{c,calls}=client(f);await c.observe();await c.propose();await c.accept();await c.fetch();await c.validate();assert.deepEqual(calls.map(x=>x.op),['observe','propose','accept','fetch','validate']);assert.equal(c.current.snapshot.observation.records[0].validation.reason,'CORE_UNAVAILABLE');assert.equal(c.current.snapshot.observation.applied,false);assert.ok(!('apply'in c));});
test('revision_and_context_pinned',async()=>{const f=await setup(),{c,calls}=client(f);await c.observe();await c.propose();assert.equal(calls[1].args.expectedRevision,f.waiting.observation.revision);assert.deepEqual(calls[1].args.context,f.pin);});
test('current_snapshot_owned',async()=>{const f=await setup(),{c}=client(f);await c.observe();assert.throws(()=>c.current.snapshot.observation.records.push({}));});
test('command_before_observe_rejected',async()=>{const f=await setup(),{c,calls}=client(f);await assert.rejects(()=>c.propose());assert.equal(calls.length,0);});
test('duplicate_sequence_rejected',async()=>{const f=await setup(),{c}=client(f);await c.observe();await assert.rejects(()=>c.observe());assert.equal(c.current.status,'UNAVAILABLE');});
test('busy_rejects_no_extra_send',async()=>{const f=await setup(),d=defer(),{c,calls}=client(f,()=>d.promise);const p=c.observe();await assert.rejects(()=>c.observe());d.resolve(f.waiting);await p;assert.equal(calls.length,1);});
test('cancel_before_send',async()=>{const f=await setup(),{c,calls}=client(f),a=new AbortController();a.abort();await assert.rejects(()=>c.observe({signal:a.signal}));assert.equal(calls.length,0);});
test('cancel_after_send_discards_late',async()=>{const f=await setup(),d=defer(),{c,calls}=client(f,()=>d.promise);const p=c.observe();c.cancel();await assert.rejects(()=>p);d.resolve(f.waiting);await new Promise(r=>setImmediate(r));assert.equal(c.current.status,'UNAVAILABLE');assert.equal(c.current.snapshot,null);assert.equal(calls.length,1);});
test('deadline_noncooperative_port_not_success',async()=>{const f=await setup(),{c,calls}=client(f,()=>new Promise(()=>{}));await assert.rejects(()=>c.observe({timeoutMs:50}));assert.equal(c.current.status,'UNAVAILABLE');assert.equal(calls.length,1);});
test('accept_response_loss_retains_plan_digest',async()=>{const f=await setup(),{c,calls}=client(f,(op)=>{if(op==='accept')throw Error('local secret detail');return structuredClone(mapped(f)[op]);});await c.observe();await c.propose();await assert.rejects(()=>c.accept());assert.equal(c.current.originalPlanDigest,f.proposed.proposal.planDigest);assert.equal(c.current.resumeRequired,true);assert.ok(!JSON.stringify(c.current).includes('secret'));assert.equal(calls.length,3);});
test('fetch_response_loss_no_replay',async()=>{const f=await setup(),{c,calls}=client(f,(op)=>{if(op==='fetch')throw Error('lost');return structuredClone(mapped(f)[op]);});await c.observe();await c.propose();await c.accept();await assert.rejects(()=>c.fetch());await assert.rejects(()=>c.fetch());assert.equal(calls.filter(c=>c.op==='fetch').length,1);assert.equal(c.current.resumeRequired,true);});
test('explicit_resume_uses_caller_digest',async()=>{const f=await setup(),{c,calls}=client(f,op=>op==='resume'?f.accepted:f.waiting);await c.observe();await c.resume(f.accepted.selection.planDigest);assert.equal(calls[1].op,'resume');assert.equal(calls[1].args.planDigest,f.accepted.selection.planDigest);});
test('resume_invalid_digest_not_sent',async()=>{const f=await setup(),{c,calls}=client(f);await c.observe();await assert.rejects(()=>c.resume('../plan'));assert.equal(calls.length,1);});
test('read_only_grant_no_propose',async()=>{const f=await setup();f.waiting.operations=['close','inquire','observe'];const{c,calls}=client(f);await c.observe();await assert.rejects(()=>c.propose());assert.equal(calls.length,1);});
test('close_discards_late_response',async()=>{const f=await setup(),d=defer(),{c}=client(f,()=>d.promise);const p=c.observe();p.catch(()=>{});await c.close();d.resolve(f.waiting);await assert.rejects(()=>p);assert.equal(c.current.status,'CLOSED');});
test('synchronous_port_throw_no_unhandled',async()=>{const f=await setup();const c=new api.FetchOwnerClient(f.pin,{request(){throw Error('sensitive');},async close(){}});await assert.rejects(()=>c.observe());assert.equal(c.current.snapshot,null);});
for(const [name,mutate] of [
 ['wrong_pin',v=>v.observation.pin.planDigest='f'.repeat(64)],
 ['extra_field',v=>v.secret='hidden'],['apply_grant',v=>v.operations.push('apply')],
 ['proposal_oversize',v=>v.proposal={id:'a'.repeat(64),planDigest:'b'.repeat(64),records:65,bytes:0,queries:0}],
 ['contradictory_progress',v=>{v.selection={planDigest:'a'.repeat(64),records:1,bytes:1};v.progress={stored:2,total:1};}],
 ['float_budget',v=>v.proposal={id:'a'.repeat(64),planDigest:'b'.repeat(64),records:1.1,bytes:1,queries:1}],
])test('reject_'+name,async()=>{const f=await setup();mutate(f.waiting);const{c}=client(f);await assert.rejects(()=>c.observe());assert.equal(c.current.snapshot,null);});
test('getter_not_executed',async()=>{const f=await setup();let n=0;Object.defineProperty(f.waiting,'operations',{get(){n++;return[]},enumerable:true});const{c}=client(f,()=>f.waiting);await assert.rejects(()=>c.observe());assert.equal(n,0);});
test('invalid_options_no_send',async()=>{const f=await setup(),{c,calls}=client(f);await assert.rejects(()=>c.observe({timeoutMs:NaN}));assert.equal(calls.length,0);});
class Element{constructor(doc,tag){this.ownerDocument=doc;this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this._text='';this.value='';this.disabled=false;}set textContent(v){this._text=v;this.children=[]}get textContent(){return this._text+this.children.map(x=>x.textContent).join('')}setAttribute(k,v){this.attrs[k]=v}append(...v){this.children.push(...v)}replaceChildren(...v){this._text='';this.children=v}addEventListener(k,f){(this.events??={})[k]=f}focus(){}setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b}close(){this.open=false}showModal(){this.open=true} }
class Document{createElement(t){return new Element(this,t)}}
test('controls_explicit_button_and_no_automatic_call',async()=>{const f=await setup(),{c,calls}=client(f),d=new Document(),root=d.createElement('div');const ui=api.mountFetchControls(root,c,'ja');assert.equal(calls.length,0);await ui.refresh();assert.match(root.textContent,/依存/);assert.equal(calls.length,1);ui.destroy();assert.equal(root.textContent,'');assert.equal(c.current.status,'CURRENT');});

const find=(root,pred)=>pred(root)?root:root.children.map(x=>find(x,pred)).find(Boolean);
async function rendererFixture(){const f=await setup(),x=client(f),d=new Document(),root=d.createElement('div');
 const lib=process.env.PAR_PRESENTER_BUILD||path.join(process.env.PAR_ROOT,'product/wp11/lib');
 const {mountReference}=await import(pathToFileURL(path.join(lib,'renderer.js')));
 const {state}=await import('../wp11/support.mjs');const note=state();note.scope={appId:f.pin.scope.appId,spaceId:f.pin.scope.spaceId,documentId:f.pin.scope.documentId};
 return{...x,f,root,note,mountReference};}
test('reference_owner_panel_no_automatic_call',async()=>{const x=await rendererFixture(),ui=x.mountReference(x.root,x.note,{fetchOwner:x.c});assert.ok(find(x.root,e=>e.attrs['data-fetch-owner']==='true'));assert.equal(x.calls.length,0);ui.destroy();assert.equal(x.c.current.status,'NOT_OBSERVED');});
test('reference_scope_mismatch_before_dom_mutation',async()=>{const x=await rendererFixture();x.note.scope.documentId='another-note';x.root.textContent='keep';assert.throws(()=>x.mountReference(x.root,x.note,{fetchOwner:x.c}),/FETCH_SCOPE_MISMATCH/);assert.equal(x.root.textContent,'keep');});
test('reference_draft_and_ime_survive_owner_observe',async()=>{const x=await rendererFixture(),ui=x.mountReference(x.root,x.note,{fetchOwner:x.c});const area=find(x.root,e=>e.dataset.test==='editor');area.value='私有の入力';area.selectionStart=6;area.selectionEnd=6;area.events.compositionstart();area.events.input();const before=ui.getDraft();const observe=find(x.root,e=>e.dataset.fetchAction==='observe');assert.ok(observe,'observe control missing');observe.onclick();for(let i=0;i<30&&x.c.current.status!=='CURRENT';i++)await new Promise(r=>setTimeout(r,2));assert.equal(x.c.current.status,'CURRENT');assert.deepEqual(ui.getDraft(),before);assert.equal(find(x.root,e=>e.dataset.test==='editor'),area);assert.equal(area.value,'私有の入力');assert.equal(x.note.document.text,'Hello');ui.destroy();});
test('reference_language_updates_owner_panel',async()=>{const x=await rendererFixture(),ui=x.mountReference(x.root,x.note,{fetchOwner:x.c});ui.setLocale('en');assert.equal(find(x.root,e=>e.dataset.fetchAction==='propose')?.textContent,'Propose');ui.destroy();});
test('reference_without_owner_unchanged',async()=>{const x=await rendererFixture(),ui=x.mountReference(x.root,x.note);assert.equal(find(x.root,e=>e.attrs['data-fetch-owner']==='true'),undefined);assert.equal(ui.getDraft().text,'Hello');ui.destroy();});
test('invalid_resume_options_do_not_change_original',async()=>{const f=await setup(),{c,calls}=client(f);await c.observe();await c.propose();await c.accept();const before=c.current.originalPlanDigest;await assert.rejects(()=>c.resume('f'.repeat(64),{timeoutMs:NaN}));await assert.rejects(()=>c.observe());assert.equal(c.current.originalPlanDigest,before);assert.equal(calls.length,4);});
test('aborted_accept_does_not_record_unsent_intent',async()=>{const f=await setup(),{c,calls}=client(f);await c.observe();await c.propose();const a=new AbortController();a.abort();await assert.rejects(()=>c.accept({signal:a.signal}));await assert.rejects(()=>c.observe());assert.equal(c.current.originalPlanDigest,null);assert.equal(calls.length,3);});
for(const [name,mutate]of[
 ['incomplete_marked_complete',v=>v.progress.state='COMPLETE_PENDING'],
 ['selection_without_progress',v=>v.progress=null],
 ['zero_selection',v=>{v.selection.records=0;v.progress.total=0;v.progress.items=[];}],
])test('reject_progress_'+name,async()=>{const f=await setup();mutate(f.accepted);const{c}=client(f,()=>f.accepted);await assert.rejects(()=>c.observe());assert.equal(c.current.snapshot,null);});

test('close_during_fetch_marks_reconcile_and_keeps_sha',async()=>{const f=await setup(),d=defer(),{c}=client(f,op=>op==='fetch'?d.promise:structuredClone(mapped(f)[op]));await c.observe();await c.propose();await c.accept();const p=c.fetch();p.catch(()=>{});await c.close();await assert.rejects(()=>p);assert.equal(c.current.status,'CLOSED');assert.equal(c.current.resumeRequired,true);assert.equal(c.current.originalPlanDigest,f.accepted.selection.planDigest);d.resolve(f.fetched);});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0);}
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'})}catch(e){cases.push({id:t.id,status:'FAIL'});console.error(t.id,e.stack)}}
if(process.env.HARNESS_RESULT_PATH)await fs.writeFile(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));
console.log(JSON.stringify({cases,result:cases.every(x=>x.status==='PASS')?'PASS':'FAIL',browser_executed:false}));process.exitCode=cases.some(x=>x.status!=='PASS')?1:0;
