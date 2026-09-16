export interface Snapshot {
    readonly revision: bigint;
    readonly payload: Uint8Array;
}
/** Capacity one; volatile state notifications, never a durable event stream. */
export declare class LatestSnapshots implements AsyncIterableIterator<Snapshot> {
    #private;
    constructor(options?: {
        maxBytes?: number;
    });
    publish(revision: string, payload: Uint8Array): void;
    [Symbol.asyncIterator](): AsyncIterableIterator<Snapshot>;
    next(): Promise<IteratorResult<Snapshot>>;
    return(): Promise<IteratorResult<Snapshot>>;
    throw(error?: unknown): Promise<IteratorResult<Snapshot>>;
}
