/** Explicit owner pipe. Not a server, and no automatic downloads. */
import {readSync} from 'node:fs';
import {loadPinnedCore,verifyManifest,validateWithCore,makeWithCore,CoreError} from './automerge.mjs';
try {
 const m=process.argv[2];if(!m)throw new CoreError('CORE_UNAVAILABLE');
 const core=await loadPinnedCore(m);
 const chunks=[];let total=0;const buffer=Buffer.alloc(65536);
 for(;;){const n=readSync(0,buffer,0,buffer.length,null);if(!n)break;total+=n;if(total>8*1024*1024)throw new CoreError('RESOURCE_LIMIT');chunks.push(Buffer.from(buffer.subarray(0,n)));}
 const input=Buffer.concat(chunks);
 const q=JSON.parse(input.toString('utf8'));let value;
 if(q.action==='identity')value=core.identity;
 else if(q.action==='validate')value=validateWithCore(core,q.request);
 else if(q.action==='make')value=makeWithCore(core,q.input);
 else throw new CoreError('UNSUPPORTED_CORE_COMMAND');
 verifyManifest(m);process.stdout.write(JSON.stringify({ok:true,value}));
} catch(e) {
 const code=e instanceof CoreError?e.code:'CORE_EXECUTION_FAILED';
 process.stdout.write(JSON.stringify({ok:false,code}));process.exitCode=code==='CORE_UNAVAILABLE'?78:1;
}
