/** A UI-facing port. A private draft receipt must never promote a shared snapshot. */
import type { Draft, Scope } from './types.js';
import type { LoadedDraft, PrivateDraftReceipt } from './draft-vault.js';
import { DraftVault } from './draft-vault.js';
export interface DraftSessionPort {
    readonly scope: Scope;
    load(): Promise<LoadedDraft>;
    save(draft: Draft, version: number, operationId: string): Promise<PrivateDraftReceipt>;
    reconcile(): Promise<'CONFIRMED' | 'NOT_CONFIRMED' | 'SUPERSEDED'>;
    close(): void;
}
export declare class VaultDraftSession implements DraftSessionPort {
    #private;
    readonly vault: DraftVault;
    constructor(vault: DraftVault);
    get scope(): Scope;
    load(): Promise<LoadedDraft>;
    save(draft: Draft, version: number, operationId: string): Promise<PrivateDraftReceipt>;
    reconcile(): Promise<'CONFIRMED' | 'NOT_CONFIRMED' | 'SUPERSEDED'>;
    close(): void;
}
/** Structural validation of a trusted host observation, not a cryptographic receipt. */
export declare function checkDraftLoad(input: unknown): LoadedDraft;
export declare function checkDraftReceipt(input: unknown, version: number, operationId: string): PrivateDraftReceipt;
