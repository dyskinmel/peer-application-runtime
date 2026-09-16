/** Local private draft encryption. Independent of the PAR wire/space key suite.
 * No key persistence, plaintext fallback, automatic domain writes or replay after uncertainty.
 */
import type { Draft, Scope, NoteState } from './types.js';
import type { DraftRow, DraftStoragePort } from './draft-storage.js';
export { DraftError } from './draft-storage.js';
export interface PreparedDraftWrite {
    readonly slot: string;
    readonly expectedVersion: number;
    readonly row: DraftRow;
    readonly digest: string;
}
export interface PrivateDraftReceipt {
    readonly version: number;
    readonly operationId: string;
    readonly slot: string;
    readonly ciphertextHash: string;
    readonly durability: DraftStoragePort['durability'];
    readonly sharedSaved: false;
    readonly replicated: false;
}
export interface LoadedDraft {
    readonly version: number;
    readonly operationId: string | null;
    readonly draft: Draft | null;
}
export declare class DraftVault {
    #private;
    readonly crypto: Crypto;
    readonly port: DraftStoragePort;
    constructor(crypto: Crypto, port: DraftStoragePort, key: Uint8Array, scope: Scope);
    get scope(): Scope;
    private guard;
    private hash;
    slot(): Promise<string>;
    private derive;
    private decode;
    load(): Promise<LoadedDraft>;
    prepare(input: Draft | null, expectedVersion: number, operationId: string): Promise<PreparedDraftWrite>;
    private prepared;
    private receipt;
    commit(input: PreparedDraftWrite): Promise<PrivateDraftReceipt>;
    inspect(input: PreparedDraftWrite): Promise<{
        readonly state: 'CONFIRMED' | 'NOT_CONFIRMED' | 'SUPERSEDED';
        readonly receipt: PrivateDraftReceipt | null;
    }>;
    close(): void;
}
/** Explicit restore only. Persistence is not authority, a CRDT merge, or a shared commit. */
export declare function restoreDraft(input: Draft, current: NoteState): Draft;
