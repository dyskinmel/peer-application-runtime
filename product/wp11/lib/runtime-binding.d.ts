/** Owner observation transport contract. Shape validation is not authentication.
 * Caller must obtain the fixed Pin and port from a trusted owner, not unknown JSON.
 * No shared write, sync, CRDT, peer discovery or authority minting is implemented.
 */
import type { Scope, NoteState, Intent } from './types.js';
export interface RuntimePin {
    readonly scope: Scope;
    readonly deviceId: string;
    readonly storeGeneration: string;
    readonly streamId: string;
}
export interface RuntimeObservation extends RuntimePin {
    readonly profile: 'par-reference-runtime-observation-v1';
    readonly sequence: string;
    readonly revision: string;
    readonly observedAt: string;
    readonly authority: {
        readonly state: 'ACTIVE' | 'CONTROL_REQUIRED' | 'MEMBERSHIP_PENDING' | 'EPOCH_PENDING' | 'CONTROL_FORK' | 'CONTROL_INVALID' | 'AUTH_PERSISTENCE_UNCERTAIN';
        readonly controlHead: string;
        readonly epoch: string;
        readonly role: 'reader' | 'editor' | 'none';
        readonly writeAuthorized: boolean;
    };
    readonly document: {
        readonly envelopeCount: number;
        readonly pendingCount: number;
        readonly envelopeSetDigest: string;
        readonly text: null;
        readonly innerValidated: false;
        readonly applied: false;
        readonly catalogComplete: false;
    };
    readonly operation: {
        readonly id: string | null;
        readonly state: 'NOT_QUERIED' | 'NOT_OBSERVED' | 'OBSERVED_COMMITTED';
        readonly commitId: string | null;
        readonly receiptVerified: boolean;
        readonly outboxState: 'pending' | 'in-flight' | 'retained' | 'rebase-required' | null;
    };
    readonly capabilities: {
        readonly observe: true;
        readonly inspectOperation: true;
        readonly sharedCommit: false;
        readonly sync: false;
        readonly crdtApply: false;
    };
    readonly restoreReadOnly: boolean;
    readonly replicationObserved: false;
    readonly globalLatestProven: false;
    readonly productQualified: false;
    readonly evidenceKind: 'owner-verified-local-observation';
}
export declare function validateRuntimeObservation(input: unknown): RuntimeObservation;
/** Construct a neutral view from actual metadata; never seed it from a synthetic UI story. */
export declare function projectRuntimeObservation(input: unknown, expected: unknown): NoteState;
export interface RuntimeObservationPort {
    observe(operationId: string | null): Promise<unknown>;
    inspectOperation(operationId: string): Promise<unknown>;
}
export type RuntimeEffectResult = {
    readonly outcome: 'observed';
    readonly observation: NoteState;
} | {
    readonly outcome: 'unknown' | 'unavailable';
};
/** A narrow effect port. Only reads/operation outcome inquiries, never mutation. */
export declare class RuntimeBinding {
    private readonly port;
    private readonly pin;
    private state;
    private busy;
    private closed;
    private observation;
    constructor(expected: unknown, initial: unknown, port: RuntimeObservationPort);
    get current(): NoteState;
    close(): void;
    private start;
    private accept;
    refresh(): Promise<NoteState>;
    execute(input: Intent): Promise<RuntimeEffectResult>;
}
