import type { FetchPin, FetchObservation } from './fetch-observation.js';
export declare const FETCH_OWNER_PROTOCOL = "par-owner-fetch-0049";
export declare const FETCH_OWNER_OPERATIONS: readonly ["accept", "close", "fetch", "inquire", "observe", "propose", "resume", "validate"];
export type FetchOwnerOperation = typeof FETCH_OWNER_OPERATIONS[number];
export interface FetchOwnerPort {
    request(operation: FetchOwnerOperation, args: unknown, signal: AbortSignal): Promise<unknown>;
    close(): Promise<void>;
}
export interface FetchOwnerOptions {
    signal?: AbortSignal;
    timeoutMs?: number;
}
interface Selection {
    readonly planDigest: string;
    readonly records: number;
    readonly bytes: number;
}
interface Proposal {
    readonly id: string;
    readonly planDigest: string | null;
    readonly records: number;
    readonly bytes: number;
    readonly queries: number;
}
interface Progress {
    readonly profile: string;
    readonly planDigest: string;
    readonly state: string;
    readonly reason: string | null;
    readonly stored: number;
    readonly total: number;
    readonly items: readonly {
        readonly envelopeId: string;
        readonly state: string;
        readonly candidateState: string | null;
    }[];
    readonly applied: false;
    readonly localCommitted: false;
    readonly replicated: false;
    readonly acknowledged: false;
    readonly observationOnly: true;
}
export interface FetchOwnerSnapshot {
    readonly profile: typeof FETCH_OWNER_PROTOCOL;
    readonly observation: FetchObservation;
    readonly proposal: Proposal | null;
    readonly selection: Selection | null;
    readonly progress: Progress | null;
    readonly resumeRequired: boolean;
    readonly operations: readonly FetchOwnerOperation[];
}
export interface FetchOwnerState {
    readonly status: 'NOT_OBSERVED' | 'BUSY' | 'CURRENT' | 'UNAVAILABLE' | 'CLOSED';
    readonly snapshot: FetchOwnerSnapshot | null;
    readonly reason: string | null;
    readonly originalPlanDigest: string | null;
    readonly resumeRequired: boolean;
}
export declare const validateFetchOwnerContext: (v: unknown) => FetchPin;
export declare class FetchOwnerClient {
    private readonly port;
    readonly pin: FetchPin;
    private readonly binding;
    private staged;
    private operation;
    private busy;
    private closed;
    private epoch;
    private aborter;
    private original;
    private mustResume;
    private state;
    constructor(pin: FetchPin, port: FetchOwnerPort);
    get current(): FetchOwnerState;
    private set;
    private currentSnapshot;
    private invoke;
    observe(opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    propose(opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    accept(opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    fetch(opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    resume(planDigest: string, opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    validate(opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    inquire(operationId: string, expectedApplyRevision: number, opts?: FetchOwnerOptions): Promise<FetchOwnerSnapshot>;
    cancel(): void;
    close(): Promise<void>;
}
export interface FetchControls {
    refresh(): Promise<void>;
    setLocale(locale: 'ja' | 'en'): void;
    destroy(): void;
}
/** Borrowed owner. This view never closes a borrowed port on destroy. */
export declare function mountFetchControls(root: HTMLElement, client: FetchOwnerClient, initialLocale?: 'ja' | 'en'): FetchControls;
export {};
