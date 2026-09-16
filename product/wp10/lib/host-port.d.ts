import type { OwnerEventPort, EventContext, Cursor } from './contracts.js';
export type HostOperation = 'open' | 'poll' | 'ack' | 'cursor' | 'cancel' | 'wait';
export interface EventHostChannel {
    request(operation: HostOperation, args: unknown, signal: AbortSignal): Promise<unknown>;
    close(): Promise<void>;
}
export interface WakeTicket {
    readonly hostId: string;
    readonly revision: string;
}
export declare class GenerationEventPort implements OwnerEventPort {
    #private;
    constructor(channel: EventHostChannel, trustedHostId: string);
    open(r: {
        context: EventContext;
        expectedCursor: Cursor | null;
    }, s: AbortSignal): Promise<unknown>;
    poll(r: {
        sessionId: string;
        limit: number;
        byteLimit: number;
    }, s: AbortSignal): Promise<unknown>;
    ack(r: {
        sessionId: string;
        token: string;
    }, s: AbortSignal): Promise<unknown>;
    cursorRead(r: {
        sessionId: string;
    }, s: AbortSignal): Promise<unknown>;
    cancel(r: {
        sessionId: string;
    }, s: AbortSignal): Promise<unknown>;
    wait(s: AbortSignal): Promise<void>;
}
