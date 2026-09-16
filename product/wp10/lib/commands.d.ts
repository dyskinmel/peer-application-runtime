import type { Kind, Decimal } from './contracts.js';
export declare const COMMAND_PROTOCOL: "par-local-event-commands-0040";
export type CommandOperation = 'publish' | 'inquire';
export interface CommandContext {
    readonly protocol: typeof COMMAND_PROTOCOL;
    readonly appId: string;
    readonly spaceId: string;
    readonly streamId: string;
    readonly epoch: Decimal;
    readonly schema: Readonly<Record<string, Kind>>;
    readonly schemaDigest: string;
    readonly issuer: string;
    readonly journalGeneration: string;
    readonly authority: 'owner-publish' | 'inquire-only';
}
export type CommandField = Readonly<{
    kind: 'text' | 'uint64' | 'int64' | 'bytes';
    value: string;
}> | Readonly<{
    kind: 'bool';
    value: boolean;
}>;
export interface PublishCommand {
    readonly operationId: string;
    readonly payload: Readonly<Record<string, CommandField>>;
    readonly parents: ReadonlyArray<string>;
}
export interface EventCommandChannel {
    request(operation: CommandOperation, args: unknown, signal: AbortSignal): Promise<unknown>;
}
export interface LocalEventCommit {
    readonly kind: 'local-committed';
    readonly operationId: string;
    readonly eventId: string;
    readonly sequence: Decimal;
    readonly replicated: false;
    readonly cancellationRequested: boolean;
}
export interface CommandCancelled {
    readonly kind: 'cancelled';
    readonly operationId: string;
    readonly phase: 'before-send' | 'before-commit';
}
export interface CommandRejected {
    readonly kind: 'rejected';
    readonly operationId: string;
    readonly code: string;
}
export interface LocalOutcomeUnknown {
    readonly kind: 'outcome-unknown';
    readonly operationId: string;
    readonly code: 'LOCAL_OUTCOME_UNKNOWN';
}
export interface LocalEventAbsent {
    readonly kind: 'not-found-local';
    readonly operationId: string;
}
export type PublishResult = LocalEventCommit | CommandCancelled | CommandRejected | LocalOutcomeUnknown;
export type InquiryResult = LocalEventCommit | CommandCancelled | CommandRejected | LocalEventAbsent;
export declare function commandContext(value: unknown): CommandContext;
/** Exact bounded copy for both direct commands and retained client input.
 * This validates data, not caller authority or persistence across process restart.
 */
export declare function publishCommand(value: unknown, context: CommandContext): PublishCommand;
/** An owner-injected port, or ConnectedCommandChannel over a private descriptor.
 * A failed/unknown exchange is terminal for this client: rebind explicitly before
 * inquiry/retry. Read-only not-found-local is an observation, never replay consent.
 * Programmer input errors reject with EventBindingError(COMMAND_INPUT_INVALID).
 * Operational outcomes are discriminated unions; none of them automatically ACK.
 */
export declare class EventCommands {
    #private;
    constructor(channel: EventCommandChannel, expectedContext: CommandContext, hostId: string, options?: {
        requestTimeoutMs?: number;
    });
    publish(input: PublishCommand, options?: {
        signal?: AbortSignal;
    }): Promise<PublishResult>;
    inquire(operationId: string, options?: {
        signal?: AbortSignal;
    }): Promise<InquiryResult>;
    /** Stop this client; the embedding still owns and explicitly closes its channel. */
    close(): void;
    stats(): Readonly<{
        closed: boolean;
        busy: boolean;
        reconciliationRequired: boolean;
    }>;
}
