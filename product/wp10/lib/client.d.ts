import type { CommandContext, PublishCommand, PublishResult, InquiryResult } from './commands.js';
import type { OwnedEventCommandChannel, EventClientSnapshot, EventClientView } from './client-state.js';
/** One retained operation and one active exchange per client. expectedContext is
 * pinned for life. The caller owns durable retention of the original input/ID.
 * A failed rebind leaves its candidate channel owned by the caller.
 */
export declare class EventCommandClient {
    #private;
    constructor(expectedContext: CommandContext, options?: {
        requestTimeoutMs?: number;
        cleanupTimeoutMs?: number;
    });
    get current(): EventClientSnapshot;
    get view(): EventClientView;
    rebind(channel: OwnedEventCommandChannel, observedContext: CommandContext, hostId: string): void;
    restoreUnknown(input: PublishCommand): void;
    publish(input: PublishCommand, options?: {
        signal?: AbortSignal;
    }): Promise<PublishResult>;
    inquire(operationId: string, options?: {
        signal?: AbortSignal;
    }): Promise<InquiryResult>;
    /** Await bounded cleanup attempts. failed stays true on rejection or timeout;
     * pending=0 in that case is NOT proof that native resources were released. */
    waitForCleanup(): Promise<void>;
    close(): void;
}
