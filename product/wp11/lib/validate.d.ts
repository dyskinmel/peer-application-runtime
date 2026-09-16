import type { NoteState, Preview, Scope, Command, Draft, DraftEvent } from './types.js';
export declare class ContractError extends Error {
    readonly code: string;
    readonly detail: string;
    constructor(code: string, detail?: string);
}
export declare function check(ok: unknown, detail: string, code?: string): asserts ok;
export declare function record(v: unknown, keys: readonly string[]): Record<string, unknown>;
export declare function string(v: unknown, max?: number, min?: number): asserts v is string;
export declare function enumValue(v: unknown, vs: readonly unknown[]): void;
export declare function count(v: unknown, max?: number): asserts v is number;
export declare function u64(v: unknown): asserts v is string;
export declare function bool(v: unknown): void;
export declare function list(v: unknown, max: number, fn: (item: unknown) => void): asserts v is unknown[];
export declare function scope(v: unknown): asserts v is Scope;
export declare function scopeKey(v: Scope): string;
export declare function previewValue(v: unknown): asserts v is Preview;
export declare function freeze<T>(v: T): T;
export declare function clone<T>(v: T): T;
/** Stable comparison for validated JSON. Not a signature, hash or authorization token. */
export declare function canonical(v: unknown): string;
export declare function validateState(v: unknown): NoteState;
export declare function validateCommand(v: unknown): Command;
export declare function validateDraft(v: unknown): Draft;
export declare function validateDraftEvent(v: unknown): DraftEvent;
