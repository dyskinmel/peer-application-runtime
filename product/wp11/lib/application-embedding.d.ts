import type { ApplicationContext, ApplicationOwnerPort, CallerIntentStore, OriginalApplication, ApplicationSnapshot, ApplicationOptions } from './application-owner.js';
export type EmbeddingOperation = 'restore' | 'stage' | 'observe' | 'prepare' | 'dispatch' | 'inquire' | 'retire' | 'abandon';
export interface EmbeddingState {
    readonly lifecycle: 'DETACHED' | 'ATTACHED' | 'DETACHING' | 'CLEANUP_UNCONFIRMED';
    readonly caller: 'UNLOADED' | 'EMPTY' | 'SAVED' | 'UNCERTAIN';
    readonly original: OriginalApplication | null;
    readonly dispatchAttempted: boolean;
    readonly snapshot: ApplicationSnapshot | null;
    readonly busy: boolean;
    readonly needsInquiry: boolean;
    readonly reason: string | null;
    readonly localExperiment: boolean;
    readonly pendingStore: number;
    readonly pendingRequests: number;
}
export declare class ApplicationEmbedding {
    private readonly store;
    readonly context: ApplicationContext;
    readonly targets: readonly string[];
    readonly localExperiment: boolean;
    private readonly key;
    private readonly trackedStore;
    private client;
    private lifecycle;
    private caller;
    private original;
    private attempted;
    private inquiry;
    private why;
    private busy;
    private epoch;
    private invalidated;
    private cancelled;
    private storePending;
    private requestsPending;
    private actionPending;
    private closing;
    private portClosed;
    private portCloseFailed;
    private viewOwned;
    private readonly listeners;
    constructor(context: ApplicationContext, store: CallerIntentStore, values: readonly string[], options?: {
        localExperiment?: boolean;
    });
    private trackStore;
    private remember;
    get current(): EmbeddingState;
    subscribe(fn: () => void): () => void;
    private notify;
    assertViewAvailable(): void;
    acquireView(): () => void;
    /** Takes ownership only on success. Failed attachment leaves the supplied port with its caller. */
    attach(context: ApplicationContext, port: ApplicationOwnerPort): void;
    private idle;
    private run;
    private readRecord;
    /** Read only; never creates a record, connection, intent or dispatch marker. */
    restore(): Promise<void>;
    /** Separate explicit local action. The UI never invents or replaces an ID. */
    stage(operationId: string, expectedRevision: number): Promise<void>;
    can(op: EmbeddingOperation): boolean;
    observe(options?: ApplicationOptions): Promise<ApplicationSnapshot>;
    prepare(options?: ApplicationOptions): Promise<ApplicationSnapshot>;
    private action;
    dispatch(o?: ApplicationOptions): Promise<ApplicationSnapshot>;
    inquire(o?: ApplicationOptions): Promise<ApplicationSnapshot>;
    retire(o?: ApplicationOptions): Promise<ApplicationSnapshot>;
    abandon(o?: ApplicationOptions): Promise<ApplicationSnapshot>;
    cancel(): void;
    /** Authority changes require a separately reviewed binding; no automatic migration. */
    invalidate(): Promise<void>;
    /** The retained close promise is not retried after a failure. No persistent record is removed. */
    detach(): Promise<void>;
    /** Explicitly poll a late cooperative completion; never repeats close or cancels finalizers. */
    checkCleanup(): boolean;
}
