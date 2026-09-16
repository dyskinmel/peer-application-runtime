import type {Intent,NoteState} from './types.js';
import {validateState,validateCommand,check,canonical,freeze,scopeKey} from './validate.js';
import {present,matchingPreview} from './presenter.js';
/** Preflight only. The runtime MUST revalidate authority and revision at commit. */
export function prepareCommand(current:unknown,input:unknown):Intent {
 const s=validateState(current),c=validateCommand(input);
 check(c.expectedRevision===s.revision&&c.sequence===s.sequence&&c.streamId===s.streamId&&scopeKey(c.scope)===scopeKey(s.scope),'snapshot binding','STALE_VIEW');
 const a=present(s).actions.find(a=>a.kind===c.kind);check(a,'action not offered','ACTION_NOT_OFFERED');check(a.enabled,a.disabledReason??'disabled','ACTION_DISABLED');
 if(a.confirmation!=='none'){check(c.confirmation!==null,'preview required','CONFIRMATION_REQUIRED');check(canonical(c.confirmation)===canonical(matchingPreview(s,c.kind)),'preview changed','STALE_CONFIRMATION');}
 else check(c.confirmation===null,'unexpected confirmation');
 if(c.kind==='inspect-operation'){const expected=s.surface==='rpc'?s.rpc.operationId:s.local.operationId;check(c.operationId===expected,'original operation required','OPERATION_MISMATCH');}
 return freeze({kind:'intent',command:c,effectExecuted:false,requiresDomainRevalidation:true,recoveryActivation:c.kind==='activate-recovery'?'read-only':null});
}
/** Sequences are ordered only inside the same stream+scope, never revision strings. */
export function advanceSnapshot(previous:unknown,next:unknown):NoteState{
 const a=validateState(previous),b=validateState(next);
 check(a.streamId===b.streamId&&scopeKey(a.scope)===scopeKey(b.scope),'stream/scope changed','STALE_VIEW');
 const equal=canonical(a)===canonical(b);const x=BigInt(a.sequence),y=BigInt(b.sequence);
 check(y>=x,'older snapshot','STALE_VIEW');
 if(y===x||a.revision===b.revision)check(equal,'revision reused for changed observation','REVISION_REUSED');
 return b;
}
