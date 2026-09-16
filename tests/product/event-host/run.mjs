import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const ROOT=process.env.PAR_ROOT||process.cwd();
const tests=[];const test=(id,fn)=>tests.push({id:'event-host.node.'+id,fn});
const hostId='88'.repeat(16),sessionId='77'.repeat(16);
const ctx={protocol:'par-sdk-events-local-0038',appId:'test.app',spaceId:'11'.repeat(32),streamId:'22'.repeat(32),epoch:'1',schema:{body:'text',count:'uint64'},schemaDigest:'33'.repeat(32),issuer:'44'.repeat(32),consumerId:'55'.repeat(16),journalGeneration:'66'.repeat(32)};
const cursor={position:'0',revision:'0',eventId:null,token:'aa'};
const base=kind=>({kind,context:structuredClone(ctx),sessionId});
const wrapper=(result,revision='0')=>({protocol:'par-owner-event-host-0039',ticket:{hostId,revision},result});
const empty=()=>({...base('batch'),cursor:{...cursor},events:[],ackToken:null,hasMore:false});
const event=()=>({sequence:'1',eventId:'ab'.repeat(32),operationId:'cd'.repeat(16),parents:[],payload:{body:{kind:'text',value:'hello'},count:{kind:'uint64',value:'18446744073709551615'}},payloadBytes:40});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise}};
const signal=()=>new AbortController().signal;
let lib;
function setup(){
 assert.ok(lib?.GenerationEventPort,'generation-aware owner port not implemented');
 const calls=[];const ch={request:async(op,args,s)=>{calls.push({op,args});if(op==='open')return wrapper({...base('opened'),cursor:{...cursor}});if(op==='poll')return wrapper(empty());if(op==='cursor')return wrapper({...base('cursor'),cursor:{...cursor}});if(op==='cancel')return wrapper(base('cancelled'));if(op==='wait')return wrapper({kind:'wake',reason:'changed'},'1');throw new Error('unsupported')},close:async()=>{}};
 const port=new lib.GenerationEventPort(ch,hostId);return {ch,port,calls};
}
const reject=(p,code)=>assert.rejects(p,e=>e.code===code);
test('empty-poll-ticket-is-sent-to-wait',async()=>{const {port,calls}=setup();await port.open({context:ctx,expectedCursor:null},signal());await port.poll({sessionId,limit:1,byteLimit:1024},signal());await port.wait(signal());assert.deepEqual(JSON.parse(JSON.stringify(calls.at(-1).args)),{sessionId,ticket:{hostId,revision:'0'}})});
test('wait-without-empty-poll-is-refused',async()=>{const {port}=setup();await reject(port.wait(signal()),'WAKE_TICKET_REQUIRED')});
test('nonpoll-generation-does-not-overwrite-poll-ticket',async()=>{const {port,ch,calls}=setup();await port.open({context:ctx,expectedCursor:null},signal());await port.poll({sessionId,limit:1,byteLimit:1024},signal());const f=ch.request;ch.request=async(...a)=>a[0]==='cursor'?wrapper({...base('cursor'),cursor},'1'):f(...a);await port.cursorRead({sessionId},signal());await port.wait(signal());assert.equal(calls.at(-1).args.ticket.revision,'0')});
test('single-use-wait-ticket',async()=>{const {port}=setup();await port.open({context:ctx,expectedCursor:null},signal());await port.poll({sessionId,limit:1,byteLimit:1024},signal());await port.wait(signal());await reject(port.wait(signal()),'WAKE_TICKET_REQUIRED')});
test('deadline-is-not-data-or-ack',async()=>{const {port,ch,calls}=setup();await port.open({context:ctx,expectedCursor:null},signal());await port.poll({sessionId,limit:1,byteLimit:1024},signal());ch.request=async()=>wrapper({kind:'wake',reason:'deadline'});await port.wait(signal());assert.equal(calls.filter(x=>x.op==='ack').length,0)});
test('changed-must-advance-generation',async()=>{const {port,ch}=setup();await port.open({context:ctx,expectedCursor:null},signal());await port.poll({sessionId,limit:1,byteLimit:1024},signal());ch.request=async()=>wrapper({kind:'wake',reason:'changed'});await reject(port.wait(signal()),'PORT_INVALID')});
for(const [name,mutate] of [
 ['wrong-host',r=>r.ticket.hostId='99'.repeat(16)],['number-generation',r=>r.ticket.revision=1],['leading-zero-generation',r=>r.ticket.revision='01'],['overflow-generation',r=>r.ticket.revision='18446744073709551616'],['wrong-protocol',r=>r.protocol='old'],['extra-envelope-key',r=>r.extra=true]
])test('refuse-'+name,async()=>{const {port,ch}=setup();ch.request=async()=>{const r=wrapper({...base('opened'),cursor});mutate(r);return r};await reject(port.open({context:ctx,expectedCursor:null},signal()),'PORT_INVALID')});
test('generation-rollback-refused',async()=>{const {port,ch}=setup();ch.request=async()=>wrapper({...base('opened'),cursor},'2');await port.open({context:ctx,expectedCursor:null},signal());ch.request=async()=>wrapper(empty(),'1');await reject(port.poll({sessionId,limit:1,byteLimit:1024},signal()),'PORT_INVALID')});
test('abort-late-empty-poll-does-not-arm-wait',async()=>{const {port,ch}=setup();await port.open({context:ctx,expectedCursor:null},signal());const d=deferred(),ac=new AbortController();ch.request=()=>d.promise;const p=port.poll({sessionId,limit:1,byteLimit:1024},ac.signal);ac.abort();d.resolve(wrapper(empty()));await reject(p,'CANCELLED');await reject(port.wait(signal()),'WAKE_TICKET_REQUIRED')});
test('sdk-next-wakeup-delivers-exact-u64',async()=>{const {port,ch,calls}=setup();const orig=ch.request;let count=0;ch.request=async(...a)=>a[0]==='cancel'?wrapper(base('cancelled'),'1'):a[0]==='poll'&&++count>1?wrapper({...empty(),events:[event()],ackToken:'bb'},'1'):orig(...a);const s=await lib.EventSubscription.connect(port,ctx);const b=await s.next();assert.equal(b.value.events[0].payload.count,18446744073709551615n);assert.equal(calls.filter(c=>c.op==='ack').length,0);await s.close()});
test('sdk-close-aborts-pending-wait',async()=>{const {port,ch}=setup();const f=ch.request;ch.request=(op,args,s)=>op==='wait'?new Promise((_,j)=>s.addEventListener('abort',()=>j(new Error('abort')),{once:true})):f(op,args,s);const s=await lib.EventSubscription.connect(port,ctx);const p=s.next();await new Promise(r=>setTimeout(r,1));await s.close();assert.equal((await p).done,true)});
if(process.argv.includes('--list')){console.log(JSON.stringify(tests.map(t=>t.id).sort()));process.exit(0)}
try{lib=await import(pathToFileURL(path.join(process.env.PAR_SDK_BUILD||path.join(ROOT,'product/wp10/lib'),'index.js')))}catch{}
const cases=[];for(const t of tests){try{await t.fn();cases.push({id:t.id,status:'PASS'});console.log('PASS',t.id)}catch(e){cases.push({id:t.id,status:'FAIL'});console.error('FAIL',t.id,e)}}
if(process.env.HARNESS_RESULT_PATH)fs.writeFileSync(process.env.HARNESS_RESULT_PATH,JSON.stringify({schema_version:1,nonce:process.env.HARNESS_NONCE||'standalone',cases}));
process.exitCode=cases.every(c=>c.status==='PASS')?0:1;
