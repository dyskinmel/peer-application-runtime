import {readSync} from 'node:fs';
import {loadPinnedCore,verifyManifest,CoreError} from './automerge.mjs';
import {materializeWithCore} from './materializer.mjs';
try{
 const file=process.argv[2];if(!file)throw new CoreError('CORE_UNAVAILABLE');const core=await loadPinnedCore(file);
 const chunks=[];let size=0;const buffer=Buffer.alloc(65536);
 for(;;){const n=readSync(0,buffer,0,buffer.length,null);if(!n)break;size+=n;if(size>8*1024*1024)throw new CoreError('RESOURCE_LIMIT');chunks.push(Buffer.from(buffer.subarray(0,n)));}
 const q=JSON.parse(Buffer.concat(chunks).toString('utf8'));if(q.action!=='materialize')throw new CoreError('UNSUPPORTED_CORE_COMMAND');
 const value=materializeWithCore(core,q.request);verifyManifest(file);process.stdout.write(JSON.stringify({ok:true,value}));
}catch(e){const code=e instanceof CoreError?e.code:'CORE_EXECUTION_FAILED';process.stdout.write(JSON.stringify({ok:false,code}));process.exitCode=code==='CORE_UNAVAILABLE'?78:1;}
