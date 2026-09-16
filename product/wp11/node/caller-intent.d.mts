import type {CallerIntentStore,CallerRecord,OriginalApplication} from '../lib/application-owner.js';
/** Single trusted POSIX caller, immutable slot. Not encrypted/anti-rollback. */
export class LocalCallerIntent implements CallerIntentStore {
 constructor(root:string);
 load():Promise<CallerRecord|null>;
 save(original:OriginalApplication):Promise<void>;
 markDispatch(operationId:string):Promise<void>;
}
