import type { Draft, DraftEvent } from './types.js';
export declare function toScalarOffset(text: string, utf16: number): number;
export declare function toUtf16Offset(text: string, scalar: number): number;
export declare function createDraft(text: string, frontier: string): Draft;
export declare function reduceDraft(previous: Draft, event: DraftEvent): Draft;
/** Minimal scalar splice, not a CRDT merge/rebase. No write or success receipt occurs here. */
export declare function prepareDraftCommit(input: unknown, previous: Draft, operationId: string): {
    kind: "document.text-splice-candidate";
    operationId: string;
    expectedRevision: string;
    streamId: string;
    sequence: string;
    scope: import("./types.js").Scope;
    effectExecuted: false;
    requiresDomainRevalidation: true;
    payload: {
        path: string[];
        position: {
            scalarOffset: number;
            frontier: string;
        };
        deleteScalars: number;
        insert: string;
    };
};
/** Compose snapshot status with a separate volatile edit buffer. Never label dirty text saved. */
export declare function presentEditor(input: unknown, previous: Draft): {
    primary: import("./types.js").Message;
    draft: {
        message: import("./types.js").Message;
        schemaVersion: 1;
        text: string;
        baseText: string;
        baseFrontier: string;
        selection: {
            readonly anchor: number;
            readonly focus: number;
        };
        composing: boolean;
        dirty: boolean;
        requiresRebase: boolean;
        persisted: false;
        pendingRemote: {
            readonly text: string;
            readonly frontier: string;
            readonly sequence: import("./types.js").U64;
        } | null;
        lastRemote: {
            readonly text: string;
            readonly frontier: string;
            readonly sequence: import("./types.js").U64;
        } | null;
    };
    draftCommitEligible: boolean;
    sequence: import("./types.js").U64;
    invite: {
        readonly phase: "none" | "pending" | "review" | "stale";
        readonly role: "reader" | "editor" | "opaque-keeper";
        readonly targetDevice: string | null;
        readonly manualAvailable: boolean;
        readonly fileAvailable: boolean;
    };
    contribution: {
        readonly state: "disabled" | "review-stop" | "enabled";
        readonly storageBudget: import("./types.js").U64;
        readonly relayBudget: import("./types.js").U64;
        readonly activeLeases: number;
    };
    rpc: {
        readonly state: "idle" | "pending" | "unknown" | "completed";
        readonly operationId: string | null;
    };
    schemaVersion: 1;
    streamId: string;
    revision: string;
    snapshotTime: string;
    scope: import("./types.js").Scope;
    surface: "workspace" | "protection" | "invite" | "editor" | "recovery" | "contribution" | "diagnostics" | "connectivity" | "rpc" | "browser" | "presence";
    capabilities: import("./types.js").Capabilities;
    authority: {
        readonly state: "ready" | "pending" | "fork" | "denied" | "rebase-required" | "seed-pending";
        readonly controlHead: string;
        readonly epoch: import("./types.js").U64;
        readonly role: "owner" | "editor" | "reader" | "none";
        readonly sharedWriteAllowed: boolean;
    };
    diagnostic: "storage-full" | null;
    evidence: {
        readonly kind: "synthetic" | "runtime-observation";
        readonly references: readonly string[];
    };
    actions: readonly import("./types.js").Action[];
    pendingOperations: readonly string[];
    sharedWriteEligible: boolean;
    productQualified: false;
    local: import("./types.js").NoteState["local"] & {
        readonly message: import("./types.js").Message;
    };
    protection: import("./types.js").NoteState["protection"] & {
        readonly message: import("./types.js").Message;
        readonly observedCopies: number;
        readonly verifiedRecoverableCopies: number;
        readonly goalObserved: boolean;
    };
    connection: import("./types.js").NoteState["connection"] & {
        readonly message: import("./types.js").Message;
    };
    document: import("./types.js").NoteState["document"] & {
        readonly message: import("./types.js").Message;
    };
    recovery: import("./types.js").NoteState["recovery"] & {
        readonly message: import("./types.js").Message;
        readonly writable: false;
        readonly progress: {
            readonly kind: "bytes";
            readonly received: import("./types.js").U64;
            readonly total: import("./types.js").U64 | null;
            readonly percent: number | null;
            readonly overallPercent: null;
        };
    };
    presence: {
        readonly state: import("./types.js").NoteState["presence"];
        readonly message: import("./types.js").Message;
    };
    details: {
        readonly authority: import("./types.js").Message;
        readonly rpc: import("./types.js").Message;
        readonly scope: import("./types.js").Scope;
        readonly evidence: import("./types.js").NoteState["evidence"];
    };
};
