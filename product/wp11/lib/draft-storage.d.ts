export declare const MAX_DRAFT_ROW_BYTES: number;
export declare const MAX_DRAFT_VERSION = 1000000000;
export declare class DraftError extends Error {
    readonly code: string;
    constructor(code: string);
}
export interface DraftRow {
    readonly version: number;
    readonly value: string;
}
export interface DraftStoragePort {
    readonly durability: 'browser-best-effort' | 'posix-fsync-candidate';
    read(slot: string): Promise<DraftRow | null>;
    /** Atomic version check and publication; complete only when the storage transaction completes. */
    compareAndSwap(slot: string, expectedVersion: number, next: DraftRow): Promise<void>;
}
export declare function validateSlot(slot: unknown): asserts slot is string;
export declare function validateRow(input: unknown): DraftRow;
export declare function parseRow(text: string): DraftRow;
