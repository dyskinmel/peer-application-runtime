import type { ConnectOptions, Cursor, Delivery, EventContext, OwnerEventPort } from './contracts.js';
/** Pull-based, bounded batches. Successful iteration is never acknowledgment. */
export declare class EventSubscription implements AsyncIterableIterator<Delivery> {
    #private;
    private constructor();
    static connect(port: OwnerEventPort, expected: EventContext, options?: ConnectOptions): Promise<EventSubscription>;
    get state(): string;
    get lastCursor(): Cursor;
    [Symbol.asyncIterator](): AsyncIterableIterator<Delivery>;
    poll(): Promise<Delivery | null>;
    next(): Promise<IteratorResult<Delivery>>;
    checkpoint(): Promise<Cursor>;
    close(): Promise<void>;
    return(): Promise<IteratorResult<Delivery>>;
    throw(error?: unknown): Promise<IteratorResult<Delivery>>;
}
