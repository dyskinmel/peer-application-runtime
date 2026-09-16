/** Portable, inert presentation contracts. Decimal u64 never passes through Number. */
export declare const COMMANDS: readonly ["activate-recovery", "add-copy", "approve-invite", "choose-folder", "copy-request", "create-space", "dismiss", "export", "export-diagnostics", "export-partial", "force-stop", "import-data", "inspect-fork", "inspect-operation", "open-details", "pause-recovery", "provide-key", "retry-connect", "review-conflict", "review-contribution", "review-invite", "review-rebase", "review-relay", "verify-recovery"];
export type CommandKind = typeof COMMANDS[number];
export type U64 = string;
export type StorageClass = 'native-tested' | 'native-candidate' | 'browser-best-effort';
export type Keys = 'available' | 'missing' | 'unknown';
export interface Scope {
    readonly appId: string;
    readonly spaceId: string;
    readonly documentId: string | null;
}
export interface Capabilities {
    readonly host: 'linux' | 'macos' | 'windows' | 'ios' | 'android' | 'browser';
    readonly storageClass: StorageClass;
    readonly durableKeeperEligible: boolean;
    readonly keyProtection: 'software-encrypted' | 'os-protected' | 'hardware-wrapped' | 'hardware-nonexportable';
    readonly supportsLocalEffectTransaction: boolean;
    readonly background: 'unsupported' | 'os-scheduled' | 'persistent-process';
}
export interface Observation {
    readonly deviceId: string;
    readonly manifest: string;
    readonly byteComplete: boolean;
    readonly semanticClosure: 'verified' | 'unknown' | 'incomplete';
    readonly freshness: 'fresh' | 'stale' | 'unknown';
    readonly storageClass: StorageClass;
    readonly reachable: 'observed' | 'not-observed' | 'unknown';
    readonly observedAt: string;
}
export interface Preview {
    readonly kind: CommandKind;
    readonly revision: string;
    readonly scopeKey: string;
    readonly target: string;
    readonly planDigest: string;
    readonly impact: string;
}
export interface NoteState {
    readonly schemaVersion: 1;
    readonly streamId: string;
    readonly sequence: U64;
    readonly revision: string;
    readonly snapshotTime: string;
    readonly scope: Scope;
    readonly surface: 'workspace' | 'protection' | 'invite' | 'editor' | 'recovery' | 'contribution' | 'diagnostics' | 'connectivity' | 'rpc' | 'browser' | 'presence';
    readonly capabilities: Capabilities;
    readonly supportedCommands: readonly CommandKind[];
    readonly local: {
        readonly state: 'committed' | 'pending' | 'failed' | 'unknown';
        readonly storageClass: StorageClass;
        readonly operationId: string | null;
        readonly cancellationRequested: boolean;
    };
    readonly protection: {
        readonly root: string;
        readonly goal: number;
        readonly observations: readonly Observation[];
        readonly keys: Keys;
        readonly physicalIndependence: 'unknown' | 'declared';
    };
    readonly connection: {
        readonly state: 'offline' | 'connecting' | 'connected' | 'relay-required' | 'unknown';
        readonly peers: number;
    };
    readonly authority: {
        readonly state: 'ready' | 'pending' | 'fork' | 'denied' | 'rebase-required' | 'seed-pending';
        readonly controlHead: string;
        readonly epoch: U64;
        readonly role: 'owner' | 'editor' | 'reader' | 'none';
        readonly sharedWriteAllowed: boolean;
    };
    readonly document: {
        readonly read: 'found' | 'absent-local' | 'waiting-data' | 'tombstoned' | 'quarantined';
        readonly title: string;
        readonly text: string;
        readonly frontier: string;
        readonly innerValidated: boolean;
        readonly applied: boolean;
        readonly conflicts: readonly {
            readonly value: string;
            readonly provenance: string;
        }[];
        readonly privateDraft: boolean;
        readonly knownCatalogComplete: boolean;
        readonly missingObjects: U64;
    };
    readonly recovery: {
        readonly phase: 'idle' | 'obtaining-keys' | 'fetching' | 'verifying' | 'review' | 'read-only' | 'partial';
        readonly received: U64;
        readonly total: U64 | null;
        readonly recipientValidated: boolean;
        readonly keys: Keys;
        readonly missingObjects: U64;
    };
    readonly rpc: {
        readonly state: 'idle' | 'pending' | 'unknown' | 'completed';
        readonly operationId: string | null;
    };
    readonly invite: {
        readonly phase: 'none' | 'pending' | 'review' | 'stale';
        readonly role: 'reader' | 'editor' | 'opaque-keeper';
        readonly targetDevice: string | null;
        readonly manualAvailable: boolean;
        readonly fileAvailable: boolean;
    };
    readonly contribution: {
        readonly state: 'disabled' | 'review-stop' | 'enabled';
        readonly storageBudget: U64;
        readonly relayBudget: U64;
        readonly activeLeases: number;
    };
    readonly presence: 'recent' | 'unknown';
    readonly diagnostic: 'storage-full' | null;
    readonly previews: readonly Preview[];
    readonly evidence: {
        readonly kind: 'synthetic' | 'runtime-observation';
        readonly references: readonly string[];
    };
}
export interface Message {
    readonly key: string;
    readonly args: Readonly<Record<string, string | number>>;
}
export interface Action {
    readonly kind: CommandKind;
    readonly enabled: boolean;
    readonly disabledReason: string | null;
    readonly confirmation: 'none' | 'preview' | 'explicit-risk';
    readonly targetRevision: string;
    readonly target: string | null;
}
export type NoteViewModel = Omit<NoteState, 'supportedCommands' | 'previews' | 'local' | 'protection' | 'connection' | 'document' | 'recovery' | 'presence'> & {
    readonly primary: Message;
    readonly actions: readonly Action[];
    readonly pendingOperations: readonly string[];
    readonly sharedWriteEligible: boolean;
    readonly productQualified: false;
    readonly local: NoteState['local'] & {
        readonly message: Message;
    };
    readonly protection: NoteState['protection'] & {
        readonly message: Message;
        readonly observedCopies: number;
        readonly verifiedRecoverableCopies: number;
        readonly goalObserved: boolean;
    };
    readonly connection: NoteState['connection'] & {
        readonly message: Message;
    };
    readonly document: NoteState['document'] & {
        readonly message: Message;
    };
    readonly recovery: NoteState['recovery'] & {
        readonly message: Message;
        readonly writable: false;
        readonly progress: {
            readonly kind: 'bytes';
            readonly received: U64;
            readonly total: U64 | null;
            readonly percent: number | null;
            readonly overallPercent: null;
        };
    };
    readonly presence: {
        readonly state: NoteState['presence'];
        readonly message: Message;
    };
    readonly details: {
        readonly authority: Message;
        readonly rpc: Message;
        readonly scope: Scope;
        readonly evidence: NoteState['evidence'];
    };
};
export interface Command {
    readonly schemaVersion: 1;
    readonly kind: CommandKind;
    readonly expectedRevision: string;
    readonly streamId: string;
    readonly sequence: U64;
    readonly scope: Scope;
    readonly operationId: string;
    readonly confirmation: Preview | null;
}
export interface Intent {
    readonly kind: 'intent';
    readonly command: Command;
    readonly effectExecuted: false;
    readonly requiresDomainRevalidation: true;
    readonly recoveryActivation: 'read-only' | null;
}
export interface Draft {
    readonly schemaVersion: 1;
    readonly text: string;
    readonly baseText: string;
    readonly baseFrontier: string;
    readonly selection: {
        readonly anchor: number;
        readonly focus: number;
    };
    readonly composing: boolean;
    readonly dirty: boolean;
    readonly requiresRebase: boolean;
    readonly persisted: false;
    readonly pendingRemote: {
        readonly text: string;
        readonly frontier: string;
        readonly sequence: U64;
    } | null;
    readonly lastRemote: {
        readonly text: string;
        readonly frontier: string;
        readonly sequence: U64;
    } | null;
}
export type DraftEvent = {
    readonly type: 'composition-start' | 'composition-end' | 'accept-remote' | 'authority-changed';
} | {
    readonly type: 'input';
    readonly text: string;
    readonly anchor: number;
    readonly focus: number;
} | {
    readonly type: 'remote';
    readonly text: string;
    readonly frontier: string;
    readonly sequence: U64;
};
