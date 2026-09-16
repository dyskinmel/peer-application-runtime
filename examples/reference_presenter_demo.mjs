/** Text/JSON demonstration, not a rendered UI or backend implementation. */
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const root=process.env.PAR_ROOT;
const api=await import(pathToFileURL(path.join(process.env.PAR_PRESENTER_BUILD,'index.js')).href);
const stories=JSON.parse(fs.readFileSync(path.join(root,'product/wp11/fixtures/states.json')));
const gallery=stories.map(({sourceStory,state})=>{const vm=api.present(state);return {sourceStory,ja:api.formatMessage(vm.primary,'ja'),en:api.formatMessage(vm.primary,'en'),actions:vm.actions,documentApplied:vm.document.applied,source:'SYNTHETIC_NOT_RUNTIME_PROOF'};});
const s=stories.find(x=>x.sourceStory==='UI-002').state;
let draft=api.createDraft(s.document.text,s.document.frontier);
draft=api.reduceDraft(draft,{type:'composition-start'});
draft=api.reduceDraft(draft,{type:'input',text:'日本語を入力中',anchor:7,focus:7});
draft=api.reduceDraft(draft,{type:'remote',text:'Remote change',frontier:'other-frontier',sequence:'2'});
const editor=api.presentEditor(s,draft);
console.log(JSON.stringify({scope:'PURE_PRESENTER_CONTRACT_DEMO',gallery,ime:{text:editor.draft.text,primary:api.formatMessage(editor.primary,'ja'),pendingRemote:editor.draft.pendingRemote,commitEligible:editor.draftCommitEligible,persisted:editor.draft.persisted},noNetworkCalls:true,noDatabaseWrites:true,uiRendered:false},null,2));
