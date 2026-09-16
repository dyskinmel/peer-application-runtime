// No fake merge implementation: these exercise only framing/schema/dependency controls.
import assert from 'node:assert/strict';
import {existsSync,writeFileSync,mkdtempSync,mkdirSync,readFileSync,rmSync,symlinkSync,linkSync} from 'node:fs';
import os from 'node:os';import path from 'node:path';
import {createHash} from 'node:crypto';
const file=new URL('../../../product/wp04/automerge.mjs',import.meta.url);
assert.ok(existsSync(file),'pinned actual-engine adapter has not been implemented');
const m=await import(file.href);const cases=[];
const t=(id,fn)=>cases.push({id:'shared.core.'+id,fn});
const enc=n=>{const a=[];do{const b=n&127;n=Math.floor(n/128);a.push(b|(n?128:0));}while(n);return a;};
const frame=(n=4,kind=1)=>Buffer.from([0x85,0x6f,0x4a,0x83,0,0,0,0,kind,...enc(n),...Array(n).fill(65)]);
const bad=(fn,code)=>assert.throws(fn,e=>!code||e.code===code);
t('single_change_frame',()=>assert.equal(m.checkSingleChunk(frame()),true));
t('not_magic',()=>{let x=frame();x[0]=0;bad(()=>m.checkSingleChunk(x),'NOT_SINGLE_CHANGE');});
t('document_container_rejected',()=>bad(()=>m.checkSingleChunk(frame(2,0)),'NOT_SINGLE_CHANGE'));
t('compressed_explicitly_unsupported',()=>bad(()=>m.checkSingleChunk(frame(2,2)),'COMPRESSED_CHANGE_UNSUPPORTED'));
t('concatenated_changes_rejected',()=>bad(()=>m.checkSingleChunk(Buffer.concat([frame(),frame()])),'NOT_SINGLE_CHANGE'));
t('truncation_rejected',()=>bad(()=>m.checkSingleChunk(frame().subarray(0,-1)),'NOT_SINGLE_CHANGE'));
t('noncanonical_length_rejected',()=>bad(()=>m.checkSingleChunk(Buffer.from([0x85,0x6f,0x4a,0x83,0,0,0,0,1,0x84,0,65,65,65,65])),'NOT_SINGLE_CHANGE'));
t('oversized_rejected',()=>bad(()=>m.checkSingleChunk(Buffer.alloc(524289)),'RESOURCE_LIMIT'));
t('base64_canonical',()=>assert.equal(m.bytes(frame().toString('base64')).toString('hex'),frame().toString('hex')));
t('base64_whitespace_rejected',()=>bad(()=>m.bytes(frame().toString('base64')+'\n')));
t('base64_trailing_garbage_rejected',()=>bad(()=>m.bytes(frame().toString('base64')+'!')));
t('base64_unsafe_type',()=>bad(()=>m.bytes({toString(){throw Error('called');}})));
t('uint_bool_rejected',()=>bad(()=>m.uint(true)));
t('uint_overflow_rejected',()=>bad(()=>m.uint(2**53)));
t('lone_surrogate',()=>bad(()=>m.checkText('\ud800',100)));
t('unicode_not_normalized',()=>assert.equal(m.checkText('日本語😀e\u0301',100),'日本語😀e\u0301'));
t('metadata_actor',()=>assert.deepEqual(m.metadata({actor:'a'.repeat(64),seq:1,hash:'b'.repeat(64),deps:[]}),{actor:'a'.repeat(64),sequence:'1',hash:'b'.repeat(64),dependencies:[]}));
t('metadata_unsafe_sequence',()=>bad(()=>m.metadata({actor:'a'.repeat(64),seq:2**53,hash:'b'.repeat(64),deps:[]})));
t('metadata_duplicate_deps',()=>bad(()=>m.metadata({actor:'a'.repeat(64),seq:1,hash:'b'.repeat(64),deps:['c'.repeat(64),'c'.repeat(64)]})));
t('request_hash_order',()=>assert.equal(m.digest({b:2,a:1}),createHash('sha256').update('{"a":1,"b":2}').digest('hex')));
t('only_supported_dependency_version',()=>bad(()=>m.validatePackageInfo({name:'@automerge/automerge',version:'3.2.6',license:'MIT'}),'CORE_VERSION_UNSUPPORTED'));
t('dependency_name',()=>bad(()=>m.validatePackageInfo({name:'fake',version:'3.4.1',license:'MIT'}),'CORE_VERSION_UNSUPPORTED'));
t('unpinned_transitives_refused',()=>bad(()=>m.validatePackageInfo({name:'@automerge/automerge',version:'3.4.1',license:'MIT',dependencies:{other:'*'}}),'UNPINNED_TRANSITIVE_DEPENDENCIES'));
t('unknown_ops_refused',()=>bad(()=>m.validateOps([{action:'inc',obj:'_root',key:'title',value:1,pred:[]}],null,{actor:'a'.repeat(64),startOp:1}),'UNSUPPORTED_NOTE_OPERATION'));
t('unknown_root_field_refused',()=>bad(()=>m.validateOps([{action:'set',obj:'_root',key:'secret',value:'x',pred:[],insert:false}],null,{actor:'a'.repeat(64),startOp:1}),'UNSUPPORTED_NOTE_OPERATION'));
t('text_body_replacement_refused',()=>bad(()=>m.validateOps([{action:'makeText',obj:'_root',key:'body',pred:[],insert:false}],'1@'+'b'.repeat(64),{actor:'a'.repeat(64),startOp:1}),'UNSUPPORTED_NOTE_OPERATION'));
t('text_valid_scalar',()=>assert.equal(m.validateOps([{action:'set',obj:'1@'+'a'.repeat(64),elemId:'_head',value:'😀',pred:[],insert:true}],'1@'+'a'.repeat(64),{actor:'a'.repeat(64),startOp:2}),true));
t('text_multi_scalar_refused',()=>bad(()=>m.validateOps([{action:'set',obj:'1@'+'a'.repeat(64),elemId:'_head',value:'ab',pred:[],insert:true}],'1@'+'a'.repeat(64),{actor:'a'.repeat(64),startOp:2}),'UNSUPPORTED_NOTE_OPERATION'));
t('root_delete_refused',()=>bad(()=>m.validateOps([{action:'del',obj:'_root',key:'body',pred:[],insert:false}],null,{actor:'a'.repeat(64),startOp:2}),'UNSUPPORTED_NOTE_OPERATION'));
t('multiple_text_roots_refused',()=>bad(()=>m.validateOps([{action:'makeText',obj:'_root',key:'body',pred:[],insert:false},{action:'makeText',obj:'_root',key:'body',pred:[],insert:false}],null,{actor:'a'.repeat(64),startOp:1}),'UNSUPPORTED_NOTE_OPERATION'));

t('requested_actor_used_in_author_clone',()=>{
 const input={};let got;
 const A={clone(doc,opts){assert.equal(doc,input);got=opts;return {kind:'not-core'};}};
 assert.deepEqual(m.cloneForAuthor(A,input,'a'.repeat(64)),{kind:'not-core'});assert.deepEqual(got,{actor:'a'.repeat(64)});
});
function packageFixture(fn){const root=mkdtempSync(path.join(os.tmpdir(),'par-core-contract-'));try{
 mkdirSync(path.join(root,'dist/cjs'),{recursive:true});writeFileSync(path.join(root,'package.json'),JSON.stringify({name:'@automerge/automerge',version:'3.4.1',license:'MIT'}));
 writeFileSync(path.join(root,'dist/cjs/fullfat_node.cjs'),'// MANIFEST TEST ONLY; NOT AUTOME RGE');return fn(root);
}finally{rmSync(root,{recursive:true,force:true});}}
t('inventory_deterministic',()=>packageFixture(root=>assert.deepEqual(m.packageInventory(root),m.packageInventory(root))));
t('inventory_body_changes_digest',()=>packageFixture(root=>{const a=m.packageInventory(root);writeFileSync(path.join(root,'dist/cjs/fullfat_node.cjs'),'changed');assert.notEqual(m.packageInventory(root).digest,a.digest);}));
t('inventory_symlink_refused',()=>packageFixture(root=>{symlinkSync('package.json',path.join(root,'link'));bad(()=>m.packageInventory(root),'CORE_UNSAFE_PATH');}));
t('inventory_hardlink_refused',()=>packageFixture(root=>{linkSync(path.join(root,'package.json'),path.join(root,'link'));bad(()=>m.packageInventory(root),'CORE_UNSAFE_PATH');}));
t('inventory_case_collision_refused',()=>packageFixture(root=>{writeFileSync(path.join(root,'Package.json'),'{}');bad(()=>m.packageInventory(root),'CORE_UNSAFE_PATH');}));
t('inventory_missing_entry_refused',()=>packageFixture(root=>{rmSync(path.join(root,'dist/cjs/fullfat_node.cjs'));bad(()=>m.packageInventory(root),'CORE_ENTRY_UNSUPPORTED');}));
t('package_scripts_not_executed_by_inventory',()=>packageFixture(root=>{const p=JSON.parse(readFileSync(path.join(root,'package.json')));p.scripts={postinstall:'exit 98'};writeFileSync(path.join(root,'package.json'),JSON.stringify(p));assert.ok(m.packageInventory(root).digest);}));
t('missing_manifest_blocks',()=>bad(()=>m.verifyManifest('/not-present-par-0032/manifest.json'),'CORE_UNAVAILABLE'));
t('manifest_verified_against_entire_file_set',()=>packageFixture(root=>{const dir=mkdtempSync(path.join(os.tmpdir(),'par-pin-'));try{const f=path.join(dir,'pin.json');writeFileSync(f,JSON.stringify(m.packageInventory(root)));assert.equal(m.verifyManifest(f).version,'3.4.1');writeFileSync(path.join(root,'new-file'),'new');bad(()=>m.verifyManifest(f),'CORE_ARTIFACT_CHANGED');}finally{rmSync(dir,{force:true,recursive:true});}}));

if(process.argv.includes('--list')){console.log(JSON.stringify(cases.map(x=>x.id).sort()));process.exit(0);}
const out=[];for(const {id,fn}of cases){try{await fn();out.push({id,status:'PASS'});}catch(e){out.push({id,status:'FAIL',detail:String(e)});console.error(id,e);}}
const r={nonce:process.env.HARNESS_NONCE??'standalone',scope:'CONTRACTS_NOT_ACTUAL_AUTOMERGE',cases:out};
if(process.env.PAR_NODE_RESULT)writeFileSync(process.env.PAR_NODE_RESULT,JSON.stringify(r));
console.log(JSON.stringify(r));process.exit(out.some(x=>x.status!=='PASS')?1:0);
