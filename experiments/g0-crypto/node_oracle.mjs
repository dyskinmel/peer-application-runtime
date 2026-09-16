/** Test-only OpenSSL code route. Accept PUBLIC fixtures on stdin, never live keys.
 * No sodium, Python, or shared HPKE implementation. Same author, not an audit.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
const cat=(...x)=>Buffer.concat(x);
const text=x=>Buffer.from(x,'ascii');
function hex(x,n=null){if(typeof x!=='string'||x.length>2097152||x.length%2||!/^[0-9a-f]*$/.test(x))throw Error();const b=Buffer.from(x,'hex');if(n!==null&&b.length!==n)throw Error();return b;}
const privateKey=(b,ed=false)=>crypto.createPrivateKey({key:cat(Buffer.from(ed?'302e020100300506032b657004220420':'302e020100300506032b656e04220420','hex'),b),format:'der',type:'pkcs8'});
const publicKey=(b,ed=false)=>crypto.createPublicKey({key:cat(Buffer.from(ed?'302a300506032b6570032100':'302a300506032b656e032100','hex'),b),format:'der',type:'spki'});
const pub=(key)=>crypto.createPublicKey(key).export({format:'der',type:'spki'}).subarray(-32);
const extract=(salt,ikm)=>crypto.createHmac('sha256',salt.length?salt:Buffer.alloc(32)).update(ikm).digest();
function expand(prk,info,n){if(!Number.isInteger(n)||n<0||n>8160)throw Error();let last=Buffer.alloc(0),result=[];for(let i=1;i<=Math.ceil(n/32);i++){last=extract(prk,cat(last,info,Buffer.from([i])));result.push(last);}return cat(...result).subarray(0,n);}
const kem=Buffer.from('4b454d0020','hex'),suite=Buffer.from('48504b45002000010003','hex'),empty=Buffer.alloc(0);
const le=(s,salt,l,ikm)=>extract(salt,cat(text('HPKE-v1'),s,text(l),ikm));
const lx=(s,prk,l,info,n)=>{const size=Buffer.alloc(2);size.writeUInt16BE(n);return expand(prk,cat(size,text('HPKE-v1'),s,text(l),info),n);};
function schedule(sk,remote,enc,recipient,info){
  const dh=crypto.diffieHellman({privateKey:privateKey(sk),publicKey:publicKey(remote)});
  const secret=lx(kem,le(kem,empty,'eae_prk',dh),'shared_secret',cat(enc,recipient),32);
  const ctx=cat(Buffer.from([0]),le(suite,empty,'psk_id_hash',empty),le(suite,empty,'info_hash',info));
  const s=le(suite,secret,'secret',empty);
  return [lx(suite,s,'key',ctx,32),lx(suite,s,'base_nonce',ctx,12)];
}
function call(r){
  if(!r||typeof r!=='object'||Array.isArray(r))throw Error();
  if(r.op==='identity')return {node:process.versions.node,openssl:process.versions.openssl,independent_review:false};
  if(r.op==='hkdf')return {okm:Buffer.from(crypto.hkdfSync('sha256',hex(r.ikm),hex(r.salt),hex(r.info),r.length)).toString('hex')};
  if(r.op==='ed-sign'){
    const key=privateKey(hex(r.seed,32),true),msg=hex(r.message);
    return {pk:pub(key).toString('hex'),signature:crypto.sign(null,msg,key).toString('hex')};
  }
  if(r.op==='ed-verify')return {valid:crypto.verify(null,hex(r.message),publicKey(hex(r.pk,32),true),hex(r.signature,64))};
  if(r.op==='hpke-seal'){
    const prk=le(kem,empty,'dkp_prk',hex(r.ikmE,32)),sk=lx(kem,prk,'sk',empty,32),enc=pub(privateKey(sk)),recipient=hex(r.pkRm,32);
    const [key,nonce]=schedule(sk,recipient,enc,recipient,hex(r.info));
    const cipher=crypto.createCipheriv('chacha20-poly1305',key,nonce,{authTagLength:16});cipher.setAAD(hex(r.aad));
    const ct=cat(cipher.update(hex(r.pt)),cipher.final(),cipher.getAuthTag());return {enc:enc.toString('hex'),ct:ct.toString('hex')};
  }
  if(r.op==='hpke-open'){
    const sk=hex(r.skRm,32),enc=hex(r.enc,32),recipient=pub(privateKey(sk)),ct=hex(r.ct);
    if(ct.length<16)throw Error();const [key,nonce]=schedule(sk,enc,enc,recipient,hex(r.info));
    const cipher=crypto.createDecipheriv('chacha20-poly1305',key,nonce,{authTagLength:16});cipher.setAAD(hex(r.aad));cipher.setAuthTag(ct.subarray(-16));
    return {pt:cat(cipher.update(ct.subarray(0,-16)),cipher.final()).toString('hex')};
  }
  throw Error();
}
try{
  const input=fs.readFileSync(0);if(input.length>8388608)throw Error();const requests=JSON.parse(input);
  if(!Array.isArray(requests)||requests.length>1024)throw Error();
  console.log(JSON.stringify(requests.map(r=>{try{return call(r);}catch{return {error:'REJECTED'};}})));
}catch{process.stderr.write('INVALID_ORACLE_INPUT\n');process.exitCode=2;}
