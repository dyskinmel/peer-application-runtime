/** Synthetic, temporary local-draft demonstration. No real credentials or shared data. */
import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';
import {DraftVault,createDraft,reduceDraft} from '../product/wp11/lib/index.js';
import {FileDraftStore} from '../product/wp11/adapters/file-draft-store.mjs';
const root=await fs.mkdtemp(path.join(os.tmpdir(),'par-draft-demo-'));await fs.chmod(root,0o700);
const key=crypto.getRandomValues(new Uint8Array(32));const scope={appId:'org.example.notes',spaceId:'demo-space',documentId:'demo-note'};
try{
 const vault=new DraftVault(crypto,new FileDraftStore(root),key,scope);
 const draft=reduceDraft(createDraft('週末の計画','demo-frontier'),{type:'input',text:'週末の計画\n図書館へ行く。',anchor:0,focus:0});
 const prepared=await vault.prepare(draft,0,'demo-save');const receipt=await vault.commit(prepared);vault.close();
 const restarted=new DraftVault(crypto,new FileDraftStore(root),key,scope);const loaded=await restarted.load();
 console.log(JSON.stringify({scope:'TEMPORARY_PRIVATE_DRAFT_ONLY',receipt,restoredMatches:loaded.draft.text===draft.text,sharedWrite:false,replicated:false,keysWrittenToDisk:false},null,2));restarted.close();
}finally{key.fill(0);await fs.rm(root,{recursive:true,force:true});}
