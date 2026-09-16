/** Candidate browser adapter. Real-origin runtime qualification is a separate test.
 * Request success is NOT transaction commit. No plaintext data, key or implicit storage fallback.
 */
import {DraftError,validateRow,validateSlot} from './draft-storage.js';
import type {DraftRow,DraftStoragePort} from './draft-storage.js';
export function openIndexedDbDraftStore(factory:IDBFactory|undefined=globalThis.indexedDB,name='par-private-drafts-v1'):Promise<DraftStoragePort&{close():void}> {
 if(!factory)return Promise.reject(new DraftError('DRAFT_STORAGE_UNAVAILABLE'));
 if(!/^[a-zA-Z0-9._-]{1,80}$/.test(name))return Promise.reject(new DraftError('INVALID_DATABASE_NAME'));
 return new Promise((resolve,reject)=>{
  let settled=false;let request:IDBOpenDBRequest;
  try{request=factory.open(name,1);}catch{reject(new DraftError('DRAFT_STORAGE_UNAVAILABLE'));return;}
  request.onupgradeneeded=()=>{request.result.createObjectStore('drafts');};
  request.onerror=()=>{settled=true;reject(new DraftError('DRAFT_STORAGE_UNAVAILABLE'));};
  request.onblocked=()=>{settled=true;reject(new DraftError('DRAFT_STORAGE_BLOCKED'));};
  request.onsuccess=()=>{
   if(settled){request.result.close();return;}
   const db=request.result;let closed=false;
   db.onversionchange=()=>{closed=true;db.close();};
   function run<T>(write:boolean,op:(store:IDBObjectStore,tx:IDBTransaction,set:(value:T)=>void,fail:(err:Error)=>void)=>void):Promise<T>{
    if(closed)return Promise.reject(new DraftError('DRAFT_STORAGE_CLOSED'));
    return new Promise((ok,no)=>{
     let tx:IDBTransaction;
     try{tx=db.transaction('drafts',write?'readwrite':'readonly',write?{durability:'strict'}:undefined);}catch{no(new DraftError('DRAFT_STORAGE_UNAVAILABLE'));return;}
     let result:T;let hasResult=false;let error:Error|null=null;
     const fail=(e:Error)=>{error=e;try{tx.abort();}catch{no(e);}};
     tx.onabort=()=>no(error??new DraftError('DRAFT_TRANSACTION_ABORTED'));
     tx.onerror=()=>{error??=new DraftError('DRAFT_TRANSACTION_ABORTED');};
     tx.oncomplete=()=>{if(error)no(error);else if(hasResult)ok(result);else no(new DraftError('DRAFT_TRANSACTION_INCOMPLETE'));};
     try{op(tx.objectStore('drafts'),tx,v=>{result=v;hasResult=true;},fail);}catch(e){fail(e instanceof Error?e:new DraftError('DRAFT_STORAGE_ERROR'));}
    });
   }
   resolve({durability:'browser-best-effort',close(){closed=true;db.close();},
    read(slot){validateSlot(slot);return run(false,(store,_tx,set,fail)=>{const q=store.get(slot);q.onsuccess=()=>{try{set(q.result===undefined?null:validateRow(q.result));}catch(e){fail(e as Error);}};});},
    compareAndSwap(slot,expected,next){validateSlot(slot);const row=validateRow(next);
     if(!Number.isSafeInteger(expected)||expected<0||row.version!==expected+1)return Promise.reject(new DraftError('INVALID_VERSION'));
     return run<void>(true,(store,_tx,set,fail)=>{
      let size=0,records=0;const cursor=store.openCursor();
      cursor.onsuccess=()=>{try{const c=cursor.result;
       if(c){const r=validateRow(c.value);records++;if(c.key!==slot)size+=r.value.length;c.continue();return;}
       const old=store.get(slot);old.onsuccess=()=>{try{
        const r=old.result===undefined?null:validateRow(old.result);
        if((r?.version??0)!==expected){fail(new DraftError('DRAFT_CONFLICT'));return;}
        if((r===null&&records>=32)||size+row.value.length>64*1024*1024){fail(new DraftError('DRAFT_QUOTA'));return;}
        store.put(row,slot);set(undefined);
       }catch(e){fail(e as Error);}};
      }catch(e){fail(e as Error);}};
     });
    }
   });
  };
 });
}
