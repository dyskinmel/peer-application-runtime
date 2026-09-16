import {mountReference,DraftVault,VaultDraftSession,openIndexedDbDraftStore} from '../lib/index.js';
const states=await fetch('../fixtures/states.json').then(r=>{if(!r.ok)throw Error('Fixture load failed');return r.json();});
const root=document.querySelector('#reference-root'),scenario=document.querySelector('#scenario');let view;let current;let selectedIndex=0;
const demo=structuredClone(states.find(x=>x.state.surface==='editor').state);
demo.document.title='週末の計画';demo.document.text='やりたいことを、少しずつ。\n\n土曜日\n朝はコーヒーを淹れて、読みかけの本を読む。\n午後は散歩へ。気になった場所をここに書き留める。\n\n持っていくもの\n・ノート\n・カメラ\n・いつもの水筒';demo.document.conflicts=[];demo.document.innerValidated=false;demo.document.applied=false;
const choices=[{sourceStory:'draft-demo',state:demo},...states];
choices.forEach((x,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=i===0?'下書きを試す（合成データ）':x.sourceStory+' · '+x.state.surface;scenario.append(o);});
function select(i){selectedIndex=i;view?.destroy();current=structuredClone(choices[i].state);view=mountReference(root,current,{locale:document.querySelector('#locale').value});document.querySelector('#vault-status').textContent='';document.querySelector('#draft-key').value='';}
scenario.onchange=()=>{if(view.getDraft().dirty&&!confirm('編集中の下書きを閉じて状態を切り替えますか？未保存の内容は失われます。')){scenario.value=String(selectedIndex);return;}select(Number(scenario.value));};
document.querySelector('#locale').onchange=e=>{document.documentElement.lang=e.target.value;view.setLocale(e.target.value);};
document.querySelector('#theme').onchange=e=>{document.documentElement.dataset.theme=e.target.value;};
document.querySelector('#direction').onchange=e=>{document.body.dir=e.target.value;};
document.querySelector('#unlock').onclick=async()=>{
 const field=document.querySelector('#draft-key'),status=document.querySelector('#vault-status');const raw=field.value.trim();field.value='';
 if(!/^[0-9a-fA-F]{64}$/.test(raw)){status.textContent='鍵は64桁の16進数で指定してください。';return;}
 const key=Uint8Array.from(raw.match(/../g),b=>parseInt(b,16));let port;
 try{if(!crypto.subtle)throw Error('SECURE_CONTEXT_REQUIRED');port=await openIndexedDbDraftStore();const vault=new DraftVault(crypto,port,key,current.scope);const session=new VaultDraftSession(vault);const close=session.close.bind(session);session.close=()=>{close();port.close();};await view.attachDraftSession(session);status.textContent='鍵をメモリー内に読み込みました。DBには保存しません。';}
 catch(e){port?.close();status.textContent='永続下書きを利用できません: '+(e.code??e.name??'UNAVAILABLE');}
 finally{key.fill(0);}
};
window.addEventListener('beforeunload',e=>{if(view?.getDraft().dirty){e.preventDefault();e.returnValue='';}});select(0);
