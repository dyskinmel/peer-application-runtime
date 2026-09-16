/** PAR API CONTRACT CANDIDATE. Declarations only; no runtime is shipped. */
export type Opaque<Tag extends string> = string & { readonly __brand: Tag };
export type SpaceId = Opaque<'SpaceId'>;
export type DocumentId = Opaque<'DocumentId'>;
export type BlobId = Opaque<'BlobId'>;
export type DeviceId = Opaque<'DeviceId'>;
export type OperationId = Opaque<'OperationId'>;
export type CommitId = Opaque<'CommitId'>;
export type RootId = Opaque<'RootId'>;
export type FrontierId = Opaque<'FrontierId'>;
export type Revision = Opaque<'Revision'>;
export type SchemaId = Opaque<'SchemaId'>;
export type Cursor = Opaque<'Cursor'>;
/** Native/JS uses checked u64 bigint; JSON codecs use canonical decimal strings. */
export type UInt64 = bigint;
export type RetryHint = 'none'|'same-operation'|'reconnect'|'user-action'|'rebase';
export type ErrorCode = 'INVALID_ENCODING'|'NOT_AUTHORIZED'|'CONTROL_REQUIRED'|
 'CONTROL_FORK'|'EPOCH_REBASE_REQUIRED'|'DEPENDENCIES_PENDING'|'RESOURCE_BLOCKED'|
 'ROOT_INCOMPLETE'|'LOCAL_OUTCOME_UNKNOWN'|'RPC_OUTCOME_UNKNOWN'|'OPERATION_ID_REUSED'|
 'CANCEL_TOO_LATE'|'KEY_UNAVAILABLE'|'CURSOR_EXPIRED'|'INTEGRITY_FAILURE'|
 'NOT_FOUND_IN_SCOPE'|'STORAGE_FULL'|'UNSUPPORTED_PROFILE'|'UNSUPPORTED_SCHEMA'|
 'CANCELLED'|'DEADLINE_EXCEEDED'|'ACTOR_EQUIVOCATION'|'NO_REACHABLE_PEER';
export interface ParError {
 readonly code: ErrorCode; readonly phase: string; readonly retry: RetryHint;
 readonly operationId?: OperationId; readonly detailCode: string;
 readonly commitBoundary?:'before-commit'|'after-commit'|'unknown';
}
export type Result<T> = {readonly ok:true; readonly value:T}|{readonly ok:false; readonly error:ParError};
export interface CallOptions { readonly signal?:AbortSignal; readonly timeoutMs?:number; }
export type StorageClass = 'native-tested'|'native-candidate'|'browser-best-effort';
export interface RuntimeCapabilities {
 readonly host:'linux'|'macos'|'windows'|'ios'|'android'|'browser';
 readonly storageClass:StorageClass; readonly durableKeeperEligible:boolean;
 readonly keyProtection:'software-encrypted'|'os-protected'|'hardware-wrapped'|'hardware-nonexportable';
 readonly supportsLocalEffectTransaction:boolean;
 readonly background:'unsupported'|'os-scheduled'|'persistent-process';
}
export interface RuntimeOptions {
 readonly appId:string;
 readonly identity:{readonly mode:'platform-keystore'|'explicit-keystore';readonly reference?:string};
 readonly storage:{readonly mode:'platform-default'|'explicit-path';readonly encryption:'required';readonly path?:string};
 readonly connectivity:{readonly profile:'participants-only'|'community-assisted'|'external-assisted';
  readonly discovery:readonly ('invitation'|'known-peers'|'lan-with-permission')[];
  readonly bootstrapPeers:readonly string[]; readonly relayPeers:readonly string[]};
 readonly contribution:{readonly storeForOthers:false;readonly relayForOthers:false};
}
export type FieldDefinition =
 {readonly type:'register<string>';readonly maxUtf8Bytes:number}|
 {readonly type:'text';readonly maxUtf8Bytes:number}|
 {readonly type:'counter';readonly numeric:'int64'};
export interface SchemaManifest {readonly id:string;readonly fields:Readonly<Record<string,FieldDefinition>>;}
export interface SpaceCreateOptions {
 readonly operationId:OperationId; readonly label:string;
 readonly schemas:readonly SchemaManifest[];
 readonly replication:{readonly remoteRetainedCopies:number};
}
export interface CommitReceipt {
 readonly operationId:OperationId; readonly commitId:CommitId; readonly frontier:FrontierId;
 readonly local:'committed'; readonly storageClass:StorageClass; readonly revision:Revision;
 readonly cancellationRequested?:boolean;
}
export interface Coverage {
 readonly scope:'local-materialized'; readonly knownCatalogComplete:boolean;
 readonly missingObjects:UInt64; readonly controlHead:RootId; readonly frontier:FrontierId;
}
export interface Snapshot {
 readonly revision:Revision; readonly frontier:FrontierId;
 readonly selected:Readonly<Record<string,unknown>>;
 readonly conflicts:Readonly<Record<string,readonly {readonly value:unknown;readonly provenance:string}[]>>;
 readonly coverage:Coverage;
}
export type ReadResult =
 {readonly state:'found';readonly snapshot:Snapshot}|
 {readonly state:'absent-local';readonly scope:SpaceId}|
 {readonly state:'waiting-data';readonly missing:readonly RootId[]}|
 {readonly state:'tombstoned';readonly frontier:FrontierId}|
 {readonly state:'quarantined';readonly reason:string};
/** Offsets are Unicode scalar indices at the specified frontier, never ambiguous UTF-16 offsets. */
export interface TextPosition {readonly scalarOffset:number;readonly frontier:FrontierId;}
export interface DraftTransaction {
 set(path:readonly string[],value:string):void;
 textSplice(path:readonly string[],position:TextPosition,deleteScalars:number,insert:string):void;
 increment(path:readonly string[],delta:bigint):void;
}
export interface DocumentHandle {
 readonly id:DocumentId;
 read():Promise<Result<ReadResult>>;
 change(operationId:OperationId,edit:(tx:DraftTransaction)=>void,options?:CallOptions):Promise<Result<CommitReceipt>>;
 watch(options?:CallOptions):AsyncIterable<Result<Snapshot>>;
}
export interface DocumentStore {
 create(input:{readonly operationId:OperationId;readonly schemaId:string;readonly initial:Readonly<Record<string,unknown>>},options?:CallOptions):Promise<Result<{readonly document:DocumentHandle;readonly receipt:CommitReceipt}>>;
 open(id:DocumentId,options?:CallOptions):Promise<Result<DocumentHandle>>;
 query(input:{readonly schemaId:string;readonly limit:number;readonly cursor?:Cursor},options?:CallOptions):Promise<Result<{readonly documents:readonly DocumentId[];readonly next?:Cursor;readonly coverage:Coverage}>>;
 remove(id:DocumentId,operationId:OperationId,options?:CallOptions):Promise<Result<CommitReceipt>>;
}
export interface RetentionObservation {
 readonly deviceId:DeviceId;readonly manifest:RootId;readonly byteComplete:boolean;
 readonly semanticClosure:'verified'|'unknown'|'incomplete';
 readonly freshness:'fresh'|'stale'|'unknown';readonly storageClass:StorageClass;
 readonly reachable:'observed'|'not-observed'|'unknown';readonly observedAt:string;
}
export interface ProtectionStatus {
 readonly root:RootId;readonly local:'committed'|'pending'|'failed'|'unknown';
 readonly goal:number;readonly observations:readonly RetentionObservation[];
 readonly recoveryKeys:'available'|'missing'|'unknown';
 readonly verifiedRecoverableCopies:number;readonly physicalIndependence:'declared'|'unknown';
 readonly revision:Revision;
}
export interface Replication {
 observe(commit:CommitId,options?:CallOptions):AsyncIterable<Result<ProtectionStatus>>;
 wait(commit:CommitId,policy:{readonly remoteRetainedCopies:number;readonly timeoutMs:number},options?:CallOptions):Promise<Result<{readonly satisfied:boolean;readonly status:ProtectionStatus}>>;
}
export interface BlobStore {
 put(input:{readonly operationId:OperationId;readonly content:AsyncIterable<Uint8Array>;readonly fileName:string;readonly mimeType:string},options?:CallOptions):Promise<Result<{readonly blobId:BlobId;readonly root:RootId}>>;
 get(id:BlobId,options?:CallOptions):AsyncIterable<Result<Uint8Array>>;
}
export interface DurableEvent {
 readonly id:RootId;readonly channel:DocumentId;readonly payload:Uint8Array;
 readonly cursor:Cursor;readonly replayPossible:true;
}
export interface EventStore {
 append(input:{readonly operationId:OperationId;readonly channel:DocumentId;readonly schemaId:SchemaId;readonly payload:Uint8Array},options?:CallOptions):Promise<Result<CommitReceipt>>;
 subscribe(input:{readonly channel:DocumentId;readonly subscriber:string;readonly cursor?:Cursor},options?:CallOptions):AsyncIterable<Result<DurableEvent>>;
 acknowledge(subscriber:string,cursor:Cursor):Promise<Result<void>>;
}
export interface Presence {
 publish(channel:DocumentId,hint:Uint8Array,ttlSeconds:number):Promise<Result<void>>;
 watch(channel:DocumentId,options?:CallOptions):AsyncIterable<Result<{readonly device:DeviceId;readonly state:'recent'|'unknown';readonly hint?:Uint8Array}>>;
}
export interface Rpc {
 call(input:{readonly operationId:OperationId;readonly target:DeviceId;readonly handler:string;readonly schemaId:SchemaId;readonly payload:Uint8Array;readonly mode:'pure'|'local-idempotent'|'external-side-effect';readonly timeoutMs:number},options?:CallOptions):Promise<Result<{readonly outcome:'completed'|'unknown';readonly payload?:Uint8Array}>>;
 cancel(operationId:OperationId):Promise<Result<'cancelled-before-start'|'requested-running'|'too-late-or-unknown'>>;
}
export interface JoinRequest {readonly encoded:string;readonly fingerprint:string;}
export interface Space {
 readonly id:SpaceId;readonly docs:DocumentStore;readonly blobs:BlobStore;
 readonly events:EventStore;readonly presence:Presence;readonly rpc:Rpc;readonly replication:Replication;
 invite(request:JoinRequest,role:'reader'|'editor'|'opaque-keeper',operationId:OperationId):Promise<Result<{readonly approval:'issued'|'pending';readonly invitation?:string}>>;
 exportEncrypted(options:CallOptions):Promise<Result<{readonly manifest:RootId;readonly bytes:AsyncIterable<Uint8Array>}>>;
}
export interface Spaces {
 create(options:SpaceCreateOptions):Promise<Result<Space>>;
 open(id:SpaceId):Promise<Result<Space>>;
 createJoinRequest(invitationLocator:string):Promise<Result<JoinRequest>>;
 acceptInvitation(encoded:string):Promise<Result<Space>>;
}
export interface Runtime {
 readonly spaces:Spaces;readonly capabilities:RuntimeCapabilities;
 newOperationId():OperationId;
 lookupOperation(id:OperationId):Promise<Result<{readonly state:'committed'|'absent'|'unknown';readonly receipt?:CommitReceipt}>>;
 close():Promise<Result<void>>;
}
export declare class PeerRuntime {static open(options:RuntimeOptions):Promise<Result<Runtime>>;}

/** UI presentation contract: no domain operations inside renderers. */
export type UiCommandKind = 'activate-recovery'|'add-copy'|'approve-invite'|'choose-folder'|'copy-request'|'create-space'|'dismiss'|'export'|'export-diagnostics'|'export-partial'|'force-stop'|'import-data'|'inspect-fork'|'inspect-operation'|'open-details'|'pause-recovery'|'provide-key'|'retry-connect'|'review-conflict'|'review-contribution'|'review-invite'|'review-rebase'|'review-relay'|'verify-recovery';
export interface UiAction {
 readonly kind:UiCommandKind;readonly enabled:boolean;readonly disabledReason?:string;
 readonly confirmation:'none'|'preview'|'explicit-risk';readonly targetRevision:Revision;
}
export interface UiViewModel {
 readonly schemaVersion:1;readonly revision:Revision;readonly snapshotTime:string;
 readonly scope:string;readonly actions:readonly UiAction[];
 readonly pendingOperations:readonly OperationId[];readonly capabilities:RuntimeCapabilities;
 readonly protection?:ProtectionStatus;
}
export interface UiCommand {
 readonly kind:UiCommandKind;readonly expectedRevision:Revision;
 readonly operationId:OperationId;readonly confirmedPreviewDigest?:RootId;
}
export interface Presenter<VM extends UiViewModel> {
 snapshots(options?:CallOptions):AsyncIterable<VM>;
 dispatch(command:UiCommand):Promise<Result<void>>;
}
