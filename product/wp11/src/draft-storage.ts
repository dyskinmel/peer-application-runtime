/** Storage boundary for private, local drafts. Never a replication receipt. */
import {record,check,count,string,clone,freeze,canonical} from './validate.js';
export const MAX_DRAFT_ROW_BYTES = 10 * 1024 * 1024;
export const MAX_DRAFT_VERSION = 1_000_000_000;
export class DraftError extends Error {
  constructor(readonly code:string) { super(code); this.name='DraftError'; }
}
export interface DraftRow { readonly version:number; readonly value:string; }
export interface DraftStoragePort {
  readonly durability:'browser-best-effort'|'posix-fsync-candidate';
  read(slot:string):Promise<DraftRow|null>;
  /** Atomic version check and publication; complete only when the storage transaction completes. */
  compareAndSwap(slot:string,expectedVersion:number,next:DraftRow):Promise<void>;
}
export function validateSlot(slot:unknown):asserts slot is string {
  check(typeof slot==='string'&&/^[0-9a-f]{64}$/.test(slot),'opaque draft slot');
}
export function validateRow(input:unknown):DraftRow {
  const r=record(input,['version','value']); count(r.version,MAX_DRAFT_VERSION);
  check(r.version>0,'positive draft version'); string(r.value,MAX_DRAFT_ROW_BYTES);
  return freeze(clone(r as unknown as DraftRow));
}
export function parseRow(text:string):DraftRow {
  string(text,MAX_DRAFT_ROW_BYTES+1024);
  const parsed:unknown=JSON.parse(text);
  check(canonical(parsed)===text,'canonical row (no duplicate fields)');
  return validateRow(parsed);
}
