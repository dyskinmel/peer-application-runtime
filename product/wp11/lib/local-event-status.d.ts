/** A separate reference-app status panel. Never merge this into NoteState.local,
 * shared document state, private draft storage, CRDT apply or replica protection.
 * Input is the trusted in-process client, not a serialized peer assertion. */
import type { CommandContext, EventCommandClient, EventClientOperation, ClientConnection } from '../../wp10/lib/index.js';
export interface LocalEventStatusPanel {
    readonly profile: 'par-reference-local-event-status-0041';
    readonly scope: Readonly<{
        appId: string;
        spaceId: string;
        streamId: string;
    }>;
    readonly revision: string;
    readonly bindingGeneration: string;
    readonly operationId: string | null;
    readonly connection: ClientConnection;
    readonly outcome: EventClientOperation['kind'];
    readonly message: string;
    readonly problemCode: string | null;
    readonly eventSequence: string | null;
    readonly localReceiptPreviouslyObserved: boolean;
    readonly controls: Readonly<{
        publish: boolean;
        inquire: boolean;
        rebind: boolean;
    }>;
    readonly sharedCommit: false;
    readonly remoteProtection: false;
    readonly automaticRetry: false;
    readonly productQualified: false;
}
export declare function presentLocalEventClient(client: EventCommandClient, expectedContext: CommandContext, locale: 'ja' | 'en'): LocalEventStatusPanel;
