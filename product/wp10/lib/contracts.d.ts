/** Local owner-injected interface. Values are not cryptographic attestations. */
export type Decimal = string;
export type Kind = 'text' | 'uint64' | 'int64' | 'bool' | 'bytes';
export interface EventContext {
    readonly protocol: 'par-sdk-events-local-0038';
    readonly appId: string;
    readonly spaceId: string;
    readonly streamId: string;
    readonly epoch: Decimal;
    readonly schema: Readonly<Record<string, Kind>>;
    readonly schemaDigest: string;
    readonly issuer: string;
    readonly consumerId: string;
    readonly journalGeneration: string;
}
export interface Cursor {
    readonly position: Decimal;
    readonly revision: Decimal;
    readonly eventId: string | null;
    readonly token: string;
}
export interface OwnerEventPort {
    open(request: {
        context: EventContext;
        expectedCursor: Cursor | null;
    }, signal: AbortSignal): Promise<unknown>;
    poll(request: {
        sessionId: string;
        limit: number;
        byteLimit: number;
    }, signal: AbortSignal): Promise<unknown>;
    ack(request: {
        sessionId: string;
        token: string;
    }, signal: AbortSignal): Promise<unknown>;
    cursorRead(request: {
        sessionId: string;
    }, signal: AbortSignal): Promise<unknown>;
    cancel(request: {
        sessionId: string;
    }, signal: AbortSignal): Promise<unknown>;
    /** Must wait without spinning; wake on potential new data/authority changes.
     * Lost wakeups must be avoided by the host. No event/cursor may be dropped. */
    wait(signal: AbortSignal): Promise<void>;
}
export interface EventValue {
    readonly sequence: bigint;
    readonly eventId: string;
    readonly operationId: string;
    readonly parents: ReadonlyArray<string>;
    readonly payload: Readonly<Record<string, string | bigint | boolean | Readonly<{
        hex: string;
    }>>>;
}
export interface Delivery {
    readonly events: ReadonlyArray<EventValue>;
    readonly hasMore: boolean;
    ack(): Promise<Cursor>;
}
export interface ConnectOptions {
    readonly signal?: AbortSignal;
    readonly expectedCursor?: Cursor;
    readonly limit?: number;
    readonly byteLimit?: number;
    readonly cleanupTimeoutMs?: number;
}
export declare class EventBindingError extends Error {
    readonly code: string;
    constructor(code: string);
}
export declare const fail: (code?: string) => never;
export declare function need(ok: unknown, code?: string): asserts ok;
export declare const u64: (v: unknown) => bigint;
export declare const i64: (v: unknown) => bigint;
export declare function hex(v: unknown, bytes?: number, maxBytes?: number): string;
/** Reject accessors/custom prototypes before traversal. Not a JS Proxy sandbox. */
export declare function copyData(value: unknown, maxBytes?: number): unknown;
export declare function obj(v: unknown, keys: ReadonlyArray<string>): Record<string, unknown>;
export declare function same(a: unknown, b: unknown): boolean;
export declare function cursor(v: unknown): Cursor;
export declare function context(v: unknown): EventContext;
export declare function response(v: unknown, expected: EventContext, session: string | undefined, kind: string, keys: string[]): Record<string, unknown>;
export declare function payload(v: unknown, schema: Readonly<Record<string, Kind>>): {
    value: EventValue['payload'];
    rawMaterialBytes: number;
};
