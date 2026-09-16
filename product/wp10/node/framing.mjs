/** Preconnected local capability only. No listener, discovery, auto-reconnect or TLS.
 * The embedding owner supplies a trusted full-duplex byte stream + expectedContext.
 * No private keys are loaded here. Cancellation never proves an ACK was rolled back.
 */
import {EventBindingError,same,copyData,obj,need,hex} from '../lib/contracts.js';
const REQUEST=65536,RESPONSE=1500000;
const error=code=>new EventBindingError(code);
export class ConnectedPrivateChannel {
 #protocol;#operations;#contextValidator;
 #socket;#expected;#buf=Buffer.alloc(0);#pending=new Map();#next=0n;#closed=false;#hello;
 #readyResolve;#readyReject;#helloTimer;#timeout;#errorListener;#dataListener;#endListener;
 constructor(socket,{expectedContext,requestTimeoutMs=6000,helloTimeoutMs=3000}={},profile){
  need(typeof socket?.write==='function'&&typeof socket?.on==='function'&&typeof socket?.destroy==='function','INVALID_PORT');
  for(const n of [requestTimeoutMs,helloTimeoutMs])need(Number.isInteger(n)&&n>=10&&n<=60000,'INVALID_OPTIONS');
  this.#protocol=profile.protocol;this.#operations=new Set(profile.operations);this.#contextValidator=profile.context;
  this.#socket=socket;this.#expected=this.#contextValidator(expectedContext);this.#timeout=requestTimeoutMs;
  this.ready=new Promise((resolve,reject)=>{this.#readyResolve=resolve;this.#readyReject=reject});
  this.#helloTimer=setTimeout(()=>this.#fail('HOST_HELLO_TIMEOUT'),helloTimeoutMs);
  this.#dataListener=b=>this.#data(b);this.#errorListener=()=>this.#fail('HOST_DISCONNECTED');this.#endListener=()=>this.#fail('HOST_DISCONNECTED');
  socket.on('data',this.#dataListener);socket.on('error',this.#errorListener);socket.on('end',this.#endListener);socket.on('close',this.#endListener);
 }
 #data(chunk){
  if(this.#closed)return;
  try{
   need(Buffer.isBuffer(chunk)&&this.#buf.length+chunk.length<=2*(RESPONSE+4),'HOST_FRAME_INVALID');
   this.#buf=this.#buf.length?Buffer.concat([this.#buf,chunk]):chunk;
   while(this.#buf.length>=4){
    const n=this.#buf.readUInt32BE(0);need(n>0&&n<=RESPONSE,'HOST_FRAME_INVALID');
    if(this.#buf.length<n+4)break;
    const raw=this.#buf.subarray(4,n+4);this.#buf=this.#buf.subarray(n+4);
    const text=new TextDecoder('utf-8',{fatal:true}).decode(raw);const value=JSON.parse(text);
    // Canonical compact JSON also rejects duplicate keys, NaN, trailing data,
    // non-minimal integers and whitespace before any pending request is resolved.
    need(JSON.stringify(value)===text,'HOST_FRAME_INVALID');
    this.#message(copyData(value,RESPONSE));
   }
   if(this.#buf.length===0)this.#buf=Buffer.alloc(0);
  }catch{this.#fail('HOST_FRAME_INVALID')}
 }
 #message(v){
  if(!this.#hello){
   const r=obj(v,['v','kind','protocol','hostId','context','maxRequest','maxResponse']);
   need(r.v===1&&r.kind==='hello'&&r.protocol===this.#protocol&&r.maxRequest===REQUEST&&r.maxResponse===RESPONSE,'HOST_HELLO_INVALID');
   hex(r.hostId,16);need(same(this.#contextValidator(r.context),this.#expected),'HOST_CONTEXT_MISMATCH');
   this.#hello=Object.freeze({hostId:r.hostId,context:this.#expected});clearTimeout(this.#helloTimer);this.#readyResolve(this.#hello);return;
  }
  need(v&&typeof v==='object'&&typeof v.id==='string','HOST_FRAME_INVALID');
  const row=this.#pending.get(v.id);need(row&&row.op===v.op&&v.v===1,'HOST_RESPONSE_MISMATCH');
  const isError=Object.hasOwn(v,'error');obj(v,isError?['v','id','op','error']:['v','id','op','value']);
  if(isError)need(typeof v.error==='string'&&/^[A-Z][A-Z0-9_]{0,63}$/.test(v.error),'HOST_FRAME_INVALID');
  this.#pending.delete(v.id);clearTimeout(row.timer);row.signal.removeEventListener('abort',row.abort);
  if(!row.settled){row.settled=true;if(row.signal.aborted)row.reject(error('CANCELLED'));else if(isError)row.reject(error(v.error));else row.resolve(v.value)}
 }
 #send(value){
  const raw=Buffer.from(JSON.stringify(value),'utf8');need(raw.length>0&&raw.length<=REQUEST,'HOST_REQUEST_LIMIT');
  need(!this.#closed&&this.#socket.writableLength<=2*(REQUEST+4),'HOST_WRITE_LIMIT');
  const header=Buffer.alloc(4);header.writeUInt32BE(raw.length);
  this.#socket.write(Buffer.concat([header,raw]),e=>{if(e)this.#fail('HOST_DISCONNECTED')});
 }
 request(op,args,signal){
  try{
   need(this.#hello&&!this.#closed,'HOST_DISCONNECTED');need(this.#operations.has(op),'HOST_OPERATION_DENIED');
   if(signal?.aborted)return Promise.reject(error('CANCELLED'));
   need(typeof signal?.addEventListener==='function','INVALID_OPTIONS');
   need(this.#pending.size<2,'HOST_CHANNEL_BUSY');need(this.#next<18446744073709551615n,'HOST_ID_EXHAUSTED');
   const copied=copyData(args,REQUEST),id=String(++this.#next);
   return new Promise((resolve,reject)=>{
    const row={op,resolve,reject,signal,settled:false,timer:undefined,abort:undefined};
    const abort=(code='CANCELLED')=>{
     if(row.settled)return;row.settled=true;clearTimeout(row.timer);reject(error(code));
     // Retain correlation until the owner replies; never allow an unbounded set
     // of ignored late responses. A noncooperative owner closes after grace.
     try{this.#send({v:1,cancel:id})}catch{this.#fail('HOST_DISCONNECTED');return}
     row.timer=setTimeout(()=>this.#fail('HOST_CANCEL_TIMEOUT'),1000);
    };
    row.abort=()=>abort();this.#pending.set(id,row);signal.addEventListener('abort',row.abort,{once:true});
    row.timer=setTimeout(()=>abort('HOST_REQUEST_TIMEOUT'),this.#timeout);
    try{this.#send({v:1,id,op,args:copied})}catch{this.#fail('HOST_WRITE_LIMIT')}
   });
  }catch(e){return Promise.reject(e instanceof EventBindingError?e:error('HOST_REQUEST_INVALID'))}
 }
 #fail(code){
  if(this.#closed)return;this.#closed=true;clearTimeout(this.#helloTimer);this.#readyReject(error(code));
  for(const row of this.#pending.values()){
   clearTimeout(row.timer);row.signal.removeEventListener('abort',row.abort);
   if(!row.settled){row.settled=true;row.reject(error(code))}
  }
  this.#pending.clear();this.#buf=Buffer.alloc(0);
  this.#socket.off('data',this.#dataListener);this.#socket.off('end',this.#endListener);this.#socket.off('close',this.#endListener);
  // Keep a no-op error sink until the stream has finished destroying.
  this.#socket.off('error',this.#errorListener);this.#socket.once('error',()=>{});this.#socket.destroy();
 }
 stats(){return Object.freeze({closed:this.#closed,inflight:this.#pending.size,bufferedBytes:this.#buf.length})}
 async close(){this.#fail('HOST_DISCONNECTED')}
}
