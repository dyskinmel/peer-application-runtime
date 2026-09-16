/** Optional status/controls panel. All writes and network effects require explicit actions. */
import {ApplicationEmbedding} from './application-embedding.js';
import type {EmbeddingOperation} from './application-embedding.js';
import {presentApplicationOwner} from './application-owner.js';
import {canonical,check,ContractError} from './validate.js';
export interface ApplicationControls {setLocale(locale:'ja'|'en'):void;destroy():void;cleanup():Promise<void>;}
const words={
 title:['実験用の候補適用','Experimental candidate application'],
 disclaimer:['実コア・OS安全保管・製品認定は別です。この操作は編集中の下書きを保存・共有しません。','Real core, OS-protected storage and production qualification are separate. These operations do not save or share the edit buffer.'],
 operationId:['元の操作ID（32桁の小文字16進数）','Original operation ID (32 lowercase hex digits)'],expectedRevision:['期待する適用版（0–63）','Expected application revision (0–63)'],
 target:['固定した対象','Pinned targets'],review:['対象・元ID・影響を確認しました。再送ではありません。','I reviewed targets, original ID and impact. This is not a replay.'],
 stage:['元IDを保存','Store original ID'],restore:['元IDを再読込','Restore original ID'],observe:['状態を確認','Observe'],prepare:['適用を準備','Prepare'],dispatch:['一度だけ実行要求','Dispatch once'],inquire:['元IDで結果照会','Inquire original ID'],retire:['終了を記録','Retire explicitly'],abandon:['実行前に放棄','Abandon before dispatch'],cancel:['現在の要求を取消し','Cancel request'],disconnect:['接続を終了','Disconnect'],
 detached:['未接続。記録は保持されます。再接続は所有者側の明示操作が必要です。','Disconnected. Records retained. Reconnection must be explicitly supplied by the embedding.'],
 cleanup:['接続の解放を確認できません。再接続せず診断してください。','Cleanup is unconfirmed. Diagnose before reconnecting.'],
 stored:['元IDは読込・保存済みです。','Original ID loaded and stored.'],unknown:['元IDの保存を確認してください。自動再作成しません。','Original-ID persistence needs confirmation. No automatic replacement.']
} as const;
export function mountApplicationControls(root:HTMLElement,embedding:ApplicationEmbedding,initialLocale:'ja'|'en'='ja'):ApplicationControls {
 check(initialLocale==='ja'||initialLocale==='en','locale');
 const release=embedding.acquireView();let previousLifecycle:string|null=null;let localError:string|null=null;let locale=initialLocale,alive=true,closing:Promise<void>|null=null,reviewKey:string|null=null;
 const doc=root.ownerDocument,el=<K extends keyof HTMLElementTagNameMap>(tag:K)=>doc.createElement(tag);
 const panel=el('section');panel.className='par-application';panel.setAttribute('data-application-owner','true');
 const heading=el('h2'),disclaimer=el('p'),status=el('p'),code=el('p'),stored=el('p'),target=el('pre');
 status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.dataset.applicationStatus='true';code.dataset.applicationReason='true';target.className='par-application-targets';target.style?.setProperty('overflow-wrap','anywhere');target.style?.setProperty('white-space','pre-wrap');
 const idLabel=el('label'),id=el('input'),revLabel=el('label'),rev=el('input');id.dataset.applicationField='operationId';rev.dataset.applicationField='expectedRevision';id.type='text';rev.type='text';id.maxLength=32;rev.maxLength=2;rev.value='0';
 const idText=el('span'),revText=el('span');idLabel.append(idText,id);revLabel.append(revText,rev);
 const reviewLabel=el('label'),box=el('input'),reviewText=el('span');box.type='checkbox';box.dataset.applicationField='review';reviewLabel.append(box,reviewText);
 const buttons=el('div');buttons.className='par-buttons';const ops=['restore','observe','stage','prepare','dispatch','inquire','retire','abandon','cancel','disconnect'] as const;
 const controls=new Map<typeof ops[number],HTMLButtonElement>();
 for(const op of ops){const b=el('button');b.type='button';b.dataset.applicationAction=op;controls.set(op,b);buttons.append(b);}
 panel.append(heading,disclaimer,status,code,stored,target,idLabel,revLabel,reviewLabel,buttons);root.replaceChildren(panel);
 const text=(key:keyof typeof words)=>words[key][locale==='ja'?0:1];
 const key=()=>{const s=embedding.current;return canonical({original:s.original,snapshot:s.snapshot,attempted:s.dispatchAttempted,lifecycle:s.lifecycle,busy:s.busy});};
 function render(){
  if(!alive)return;const s=embedding.current;
  if(s.lifecycle==='ATTACHED'&&previousLifecycle!=='ATTACHED')closing=null;
  previousLifecycle=s.lifecycle;
  if(reviewKey!==key()){box.checked=false;reviewKey=null;}
  heading.textContent=text('title');disclaimer.textContent=text('disclaimer');idText.textContent=text('operationId');revText.textContent=text('expectedRevision');reviewText.textContent=text('review');
  if(s.original){id.value=s.original.operationId;rev.value=String(s.original.expectedRevision);}
  id.disabled=rev.disabled=s.original!==null||s.busy||s.lifecycle!=='ATTACHED';
  target.textContent=text('target')+'\n'+embedding.targets.join('\n');stored.textContent=text(s.caller==='SAVED'?'stored':'unknown');code.textContent=localError??s.reason??'';
  if(s.lifecycle==='CLEANUP_UNCONFIRMED')status.textContent=text('cleanup');
  else if(s.lifecycle!=='ATTACHED')status.textContent=text('detached');
  else status.textContent=presentApplicationOwner({status:s.busy?'BUSY':s.snapshot?'CURRENT':s.reason?'UNAVAILABLE':'NOT_OBSERVED',snapshot:s.snapshot,original:s.original,dispatchAttempted:s.dispatchAttempted,needsInquiry:s.needsInquiry,reason:s.reason},locale);
  for(const op of ops){const b=controls.get(op)!;b.textContent=text(op);
   if(op==='cancel')b.disabled=!s.busy;else if(op==='disconnect')b.disabled=s.lifecycle!=='ATTACHED';
   else b.disabled=!embedding.can(op)||(['dispatch','retire','abandon'].includes(op)&&(!box.checked||reviewKey!==key()));
  }
  box.disabled=s.busy||!['dispatch','retire','abandon'].some(op=>embedding.can(op as EmbeddingOperation));
 }
 box.onchange=()=>{if(box.checked)reviewKey=key();else reviewKey=null;render();};
 const beginClose=()=>{if(closing===null){closing=embedding.detach();void closing.catch(()=>{});}return closing;};
 for(const op of ops)controls.get(op)!.onclick=async()=>{
  const b=controls.get(op)!;if(!alive||b.disabled)return;
  try{
   localError=null;
   if(op==='cancel'){embedding.cancel();return;}
   if(op==='disconnect'){await beginClose();return;}
   if(['dispatch','retire','abandon'].includes(op)){check(box.checked&&reviewKey===key(),'review stale','APPLICATION_REVIEW_REQUIRED');box.checked=false;reviewKey=null;}
   if(op==='stage'){
    check(/^[0-9a-f]{32}$/.test(id.value)&&/^(0|[1-9][0-9]?)$/.test(rev.value)&&Number(rev.value)<=63,'input','APPLICATION_INPUT_INVALID');
    await embedding.stage(id.value,Number(rev.value));
   }else await embedding[op]();
  }catch(e){if(alive){localError=e instanceof ContractError?e.code:'APPLICATION_ACTION_FAILED';render();}}
  finally{render();}
 };
 const unsubscribe=embedding.subscribe(()=>{localError=null;render();});render();
 return{setLocale(next){check(next==='ja'||next==='en','locale');locale=next;box.checked=false;reviewKey=null;render();},destroy(){if(!alive)return;alive=false;unsubscribe();release();for(const b of controls.values())b.onclick=null;box.onchange=null;root.replaceChildren();void beginClose();},cleanup(){return closing??Promise.resolve();}};
}
