/** Volatile client observations, never shared-document or protection evidence. */
import type { CommandContext, EventCommandChannel, LocalEventCommit, PublishResult, LocalEventAbsent } from './commands.js';
/** Ownership transfers only on successful rebind. close must start disposal
 * immediately; asynchronous completion is observed with a bounded deadline. */
export interface OwnedEventCommandChannel extends EventCommandChannel {
    close(): void | Promise<void>;
}
export type ClientConnection = 'unbound' | 'connected' | 'rebind-required' | 'closed';
export type EventClientOperation = Readonly<{
    kind: 'idle';
}> | Readonly<{
    kind: 'publishing' | 'inquiring';
    operationId: string;
}> | Readonly<{
    kind: 'inquiry-failed';
    operationId: string;
    code: string;
}> | PublishResult | LocalEventAbsent;
export interface EventClientSnapshot {
    readonly profile: 'par-local-event-client-0041';
    readonly revision: string;
    readonly bindingGeneration: string;
    readonly context: CommandContext;
    readonly connection: ClientConnection;
    readonly hostId: string | null;
    readonly operation: EventClientOperation;
    readonly requiresInquiry: boolean;
    /** Historical local receipt, not current storage availability or remote proof. */
    readonly knownCommit: LocalEventCommit | null;
    readonly cleanup: Readonly<{
        pending: number;
        failed: boolean;
    }>;
}
export interface EventClientView {
    readonly profile: 'par-local-event-client-view-0041';
    readonly revision: string;
    readonly bindingGeneration: string;
    readonly connection: ClientConnection;
    readonly status: EventClientOperation['kind'];
    readonly operationId: string | null;
    readonly problemCode: string | null;
    readonly localReceipt: LocalEventCommit | null;
    readonly canPublish: boolean;
    readonly canInquire: boolean;
    readonly needsRebind: boolean;
    readonly requiresInquiry: boolean;
    readonly cleanupFailed: boolean;
    readonly sharedCommit: false;
    readonly remoteProtection: false;
    readonly automaticRetry: false;
}
/** Input is a trusted, immutable client snapshot, not unvalidated network JSON.
 * No payload, note text, parent bytes or authority upgrade cross this projection.
 */
export declare function projectEventClient(state: EventClientSnapshot): EventClientView;
