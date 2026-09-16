declare const PROFILE: "par-fetch-observation-local-0046";
declare const ROOT_STATES: readonly ["NOT_OBSERVED", "WAITING_DEPENDENCIES", "READY_FOR_CORE", "QUARANTINED", "WAITING_AUTHORITY", "REBASE_REQUIRED", "INVALID_DEPENDENCY_GRAPH", "RESOURCE_BLOCKED"];
declare const VALIDATION_STATES: readonly ["NOT_OBSERVED", "WAITING_DEPENDENCIES", "READY_FOR_CORE", "QUARANTINED", "WAITING_AUTHORITY", "REBASE_REQUIRED", "INVALID_DEPENDENCY_GRAPH", "RESOURCE_BLOCKED", "CORE_BLOCKED", "CORE_REJECTED", "SEMANTICALLY_VALIDATED_PENDING", "CONTRACT_CHECKED"];
declare const OP_STATES: readonly ["NOT_REQUESTED", "REQUESTED", "CORE_BLOCKED", "REJECTED", "OUTCOME_UNKNOWN", "INQUIRY_FAILED", "NOT_OBSERVED", "OBSERVED_APPLICATION_RECORD"];
export interface FetchPin {
    readonly profile: typeof PROFILE;
    readonly scope: Readonly<{
        appId: string;
        spaceId: string;
        documentId: string;
        epoch: string;
        schemaId: string;
        controlHead: string;
    }>;
    readonly planDigest: string;
    readonly targetDigest: string;
    readonly inboxGeneration: string;
    readonly storeGeneration: string;
    readonly connectionGeneration: string;
    readonly streamId: string;
}
export interface FetchObservation {
    readonly profile: typeof PROFILE;
    readonly pin: FetchPin;
    readonly sequence: string;
    readonly revision: string;
    readonly localRevision: string;
    readonly records: readonly Readonly<{
        envelopeId: string;
        state: typeof ROOT_STATES[number];
        inboxStored: boolean;
        missingInner: readonly string[];
        missingPrevious: readonly string[];
        validation: Readonly<{
            state: typeof VALIDATION_STATES[number];
            reason: string | null;
        }> | null;
    }>[];
    readonly operation: Readonly<{
        id: string | null;
        state: typeof OP_STATES[number];
        reason: string | null;
        revision: number | null;
        expectedRevision: number | null;
    }>;
    readonly innerValidated: false;
    readonly applied: false;
    readonly localCommitted: false;
    readonly replicated: false;
    readonly acknowledged: false;
    readonly productQualified: false;
}
declare function pinValue(value: unknown): FetchPin;
/** Structural validation precedes cloning/hashing, so getters and array hooks
 * cannot execute. SHA binds bytes; trust still comes from the owner/port. */
export declare function validateFetchObservation(value: unknown, expectedPin: FetchPin): Promise<FetchObservation>;
export interface FetchStatusPanel {
    readonly profile: 'par-fetch-status-panel-0046';
    readonly targets: number;
    readonly missing: number;
    readonly message: string;
    readonly disclaimer: string;
    readonly applied: false;
    readonly acknowledged: false;
    readonly automaticRetry: false;
    readonly sharedCommit: false;
    readonly remoteProtection: false;
}
export declare function presentFetchObservation(v: FetchObservation, locale: 'ja' | 'en'): FetchStatusPanel;
export interface FetchObservationPort {
    observe(): Promise<unknown>;
}
export interface FetchBindingState {
    readonly status: 'NOT_OBSERVED' | 'CHECKING' | 'CURRENT' | 'UNAVAILABLE' | 'CLOSED';
    readonly observation: FetchObservation | null;
}
export declare class FetchReadBinding {
    private readonly port;
    private readonly pin;
    private ticket;
    private sequence;
    private closed;
    private state;
    private readonly knownOperations;
    constructor(pin: FetchPin, port: FetchObservationPort);
    get current(): FetchBindingState;
    close(): void;
    refresh(): Promise<FetchBindingState>;
}
export interface FetchStatusRenderer {
    refresh(): Promise<void>;
    setLocale(locale: 'ja' | 'en'): void;
    destroy(): void;
}
/** Borrowed binding; destroying this view never closes another owner's port. */
export declare function mountFetchStatus(root: HTMLElement, binding: FetchReadBinding, initialLocale?: 'ja' | 'en'): FetchStatusRenderer;
/** Same validator used by the private fetch command transport handshake. */
export { pinValue as validateFetchPin };
