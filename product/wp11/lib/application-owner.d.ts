import type { FetchPin, FetchObservation } from './fetch-observation.js';
export declare const APPLICATION_OWNER_PROTOCOL = "par-owner-application-0052";
export declare const APPLICATION_OWNER_OPERATIONS: readonly ["abandon", "close", "dispatch", "inquire", "observe", "prepare", "retire"];
export type ApplicationOwnerOperation = typeof APPLICATION_OWNER_OPERATIONS[number];
export interface ApplicationContext {
    readonly profile: typeof APPLICATION_OWNER_PROTOCOL;
    readonly document: FetchPin;
    readonly journalId: string;
    readonly bindingDigest: string;
}
export interface OriginalApplication {
    readonly profile: 'par-caller-application-0052';
    readonly ownerKey: string;
    readonly operationId: string;
    readonly expectedRevision: number;
    readonly targets: readonly string[];
}
export interface CallerRecord {
    readonly original: OriginalApplication;
    readonly dispatchAttempted: boolean;
}
export interface CallerIntentStore {
    load(): Promise<CallerRecord | null>;
    /** Durable create-only or identical readback. Failure can mean stored-but-unacknowledged. */
    save(original: OriginalApplication): Promise<void>;
    /** Durable exclusive marker. Repeating it MUST fail, even for the same ID. */
    markDispatch(operationId: string): Promise<void>;
}
export interface ApplicationOwnerPort {
    request(op: ApplicationOwnerOperation, args: unknown, signal: AbortSignal): Promise<unknown>;
    close(): Promise<void>;
}
export interface ApplicationOptions {
    signal?: AbortSignal;
    timeoutMs?: number;
}
export interface ApplicationIntentView {
    readonly operationId: string;
    readonly expectedRevision: number;
    readonly targets: readonly string[];
    readonly digest: string;
}
export interface ApplicationReceipt {
    readonly profile: string;
    readonly operationId: string;
    readonly revision: number;
    readonly heads: readonly string[];
    readonly inputIds: readonly string[];
    readonly eventDigest: string;
    readonly candidatePersisted: true;
    readonly innerValidated: boolean;
    readonly applied: boolean;
    readonly replicated: false;
    readonly phase: string;
    readonly productQualified: false;
}
export interface ApplicationJournalView {
    readonly state: 'EMPTY' | 'PREPARED' | 'DISPATCHED' | 'OBSERVED' | 'RETIRED' | 'ABANDONED';
    readonly intentDigest: string | null;
    readonly operationId: string | null;
    readonly receipt: ApplicationReceipt | null;
    readonly sequence: number;
    readonly replayAllowed: false;
    readonly applied: false;
    readonly replicated: false;
    readonly acknowledged: false;
    readonly productQualified: false;
    readonly operationState: string;
    readonly reason: string | null;
    readonly needsInquiry: boolean;
}
export interface ApplicationSnapshot {
    readonly profile: typeof APPLICATION_OWNER_PROTOCOL;
    readonly context: ApplicationContext;
    readonly observation: FetchObservation;
    readonly journal: ApplicationJournalView;
    readonly intent: ApplicationIntentView | null;
    readonly operations: readonly ApplicationOwnerOperation[];
    readonly capability: 'LOCAL_EXPERIMENT' | 'READ_ONLY_UNQUALIFIED';
}
export interface ApplicationClientState {
    readonly status: 'NOT_OBSERVED' | 'BUSY' | 'CURRENT' | 'UNAVAILABLE' | 'CLOSED';
    readonly snapshot: ApplicationSnapshot | null;
    readonly original: OriginalApplication | null;
    readonly dispatchAttempted: boolean;
    readonly needsInquiry: boolean;
    readonly reason: string | null;
}
export declare function validateApplicationContext(value: unknown): ApplicationContext;
export declare function applicationOwnerKey(context: ApplicationContext): string;
export declare function validateOriginalApplication(value: unknown): OriginalApplication;
export declare class ApplicationOwnerClient {
    private readonly port;
    private readonly store;
    readonly context: ApplicationContext;
    private readonly key;
    private busy;
    private closed;
    private epoch;
    private aborter;
    private original;
    private attempted;
    private needsInquiry;
    private sequence;
    private journalSequence;
    private knownReceipt;
    private state;
    constructor(context: ApplicationContext, port: ApplicationOwnerPort, store: CallerIntentStore);
    get current(): ApplicationClientState;
    private set;
    private idle;
    private currentFor;
    restore(): Promise<void>;
    private invoke;
    observe(opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    prepare(operationId: string, expectedRevision: number, values: readonly string[], opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    private action;
    dispatch(opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    inquire(opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    retire(opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    abandon(opts?: ApplicationOptions): Promise<ApplicationSnapshot>;
    cancel(): void;
    close(): Promise<void>;
}
export declare function presentApplicationOwner(state: ApplicationClientState, locale: 'ja' | 'en'): string;
