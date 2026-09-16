/** Read-only schema4 presentation boundary. JSON validation is not authentication.
 * The fixed pin and port come from a trusted owner. Candidate notes never cross
 * this contract. No commit, sync, CRDT execution or permission is created here.
 */
import type { Scope, NoteState, Message } from './types.js';
export interface ApplicationPin {
    readonly scope: Scope & {
        readonly documentId: string;
        readonly epoch: string;
        readonly schemaId: string;
    };
    readonly storeGeneration: string;
    readonly certificateDigest: string;
    readonly streamId: string;
    readonly engineDigest: string | null;
}
export interface ApplicationObservation extends ApplicationPin {
    readonly profile: 'par-application-observation-local-0036';
    readonly sequence: string;
    readonly revision: string;
    readonly observedAt: string;
    readonly authority: {
        readonly state: 'ACTIVE';
        readonly controlHead: string;
        readonly epoch: string;
        readonly readerAuthorized: true;
    };
    readonly application: {
        readonly state: 'EMPTY' | 'CANDIDATE_ONLY' | 'CORE_RECHECK_REQUIRED' | 'VALIDATED_LOCAL_VIEW';
        readonly revision: number;
        readonly eventDigest: string | null;
        readonly heads: readonly string[];
        readonly inputCount: number;
        readonly evidenceClass: 'none' | 'candidate' | 'core-validated';
        readonly note: {
            readonly title: string;
            readonly body: string;
            readonly titleConflicts: readonly string[];
        } | null;
        readonly innerValidated: boolean;
        readonly applied: boolean;
        readonly recheckedCoreDigest: string | null;
    };
    readonly operation: {
        readonly id: string | null;
        readonly state: 'NOT_QUERIED' | 'NOT_OBSERVED' | 'OBSERVED_CANDIDATE' | 'OBSERVED_APPLICATION_RECORD';
        readonly revision: number | null;
        readonly eventDigest: string | null;
    };
    readonly capabilities: {
        readonly observe: true;
        readonly inspectApplication: true;
        readonly sharedCommit: false;
        readonly sync: false;
        readonly apply: false;
    };
    readonly restoreReadOnly: boolean;
    readonly catalogComplete: false;
    readonly replicationObserved: false;
    readonly globalLatestProven: false;
    readonly productQualified: false;
    readonly evidenceKind: 'trusted-owner-application-observation';
}
export declare function validateApplicationPin(input: unknown): ApplicationPin;
export declare function validateApplicationObservation(input: unknown): ApplicationObservation;
export declare function applicationNotice(input: unknown): Message;
/** Application record persistence is NOT a local-edit commit acknowledgement. */
export declare function projectApplicationObservation(input: unknown, expected: unknown): NoteState;
export interface ApplicationObservationPort {
    observe(operationId: string | null): Promise<unknown>;
}
export type ApplicationBindingStatus = 'CURRENT' | 'CHECKING' | 'UNAVAILABLE' | 'CLOSED';
/** Explicit reads only. Erase exposed note state before I/O and on every failure.
 * This does not erase strings securely, nor erase separately-owned private drafts.
 */
export declare class ApplicationReadBinding {
    private readonly port;
    private readonly pin;
    private last;
    private view;
    private busy;
    private closed;
    private phase;
    private readonly knownOperations;
    constructor(expected: unknown, initial: unknown, port: ApplicationObservationPort);
    get current(): NoteState;
    get status(): ApplicationBindingStatus;
    get observation(): ApplicationObservation | null;
    private rememberOperation;
    private mask;
    close(): void;
    refresh(operationId?: string | null): Promise<NoteState>;
}
