#!/usr/bin/env node
/** Inspect only. No download, installer, npm scripts or implicit trust promotion. */
import {packageInventory,verifyManifest,CoreError} from '../product/wp04/automerge.mjs';
import {writeFileSync,openSync,fsyncSync,closeSync,lstatSync} from 'node:fs';
import path from 'node:path';
try {
 const [command,root,out,expected]=process.argv.slice(2);
 if(command==='verify') {console.log(JSON.stringify({result:'VERIFIED_BYTES_NOT_PUBLISHER_AUTHENTICITY',artifact:verifyManifest(root)},null,2));}
 else if(command==='inspect') {console.log(JSON.stringify(packageInventory(root),null,2));}
 else if(command==='pin') {
  if(!out||!path.isAbsolute(out)||!/^[a-f0-9]{64}$/.test(expected??''))throw new CoreError('EXPECTED_TREE_DIGEST_REQUIRED');
  const manifest=packageInventory(root);if(manifest.digest!==expected)throw new CoreError('CORE_ARTIFACT_CHANGED');
  const parent=path.dirname(out),st=lstatSync(parent);if(!st.isDirectory()||st.isSymbolicLink())throw new CoreError('CORE_UNSAFE_PATH');
  const fd=openSync(out,'wx',0o600);try {writeFileSync(fd,JSON.stringify(manifest,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}
  const dir=openSync(parent,'r');try{fsyncSync(dir);}finally{closeSync(dir);}
  console.log(JSON.stringify({result:'PIN_CREATED',digest:manifest.digest,path:out,publisherAuthenticityVerified:false}));
 } else {console.error('Usage: node tools/automerge_artifact.mjs inspect /absolute/extracted/package\n  pin /absolute/package /absolute/new-manifest.json REVIEWED_TREE_DIGEST\n  verify /absolute/manifest.json');process.exitCode=2;}
} catch(e) {console.error(JSON.stringify({result:'REFUSED',code:e.code??'ARTIFACT_IO_FAILURE'}));process.exitCode=1;}
