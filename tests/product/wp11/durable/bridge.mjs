/** Test-only host bridge: real Node encrypted file storage, never an app transport. */
import {DraftVault} from '../../../../product/wp11/lib/draft-vault.js';
import {FileDraftStore} from '../../../../product/wp11/adapters/file-draft-store.mjs';
let text='';for await(const p of process.stdin){text+=p;if(text.length>8*1024*1024)throw Error('TEST_INPUT_TOO_LARGE');}
const input=JSON.parse(text);const scope={appId:'org.example.notes',spaceId:'space-1',documentId:'note-1'};
const v=new DraftVault(crypto,new FileDraftStore(process.argv[2]),new Uint8Array(32).fill(42),scope);
try{let result;if(input.action==='load')result=await v.load();else if(input.action==='save')result=await v.commit(await v.prepare(input.draft,input.version,input.operationId));else throw Error('TEST_OPERATION_DENIED');console.log(JSON.stringify(result));}finally{v.close();}
