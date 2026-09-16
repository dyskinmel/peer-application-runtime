import type { NoteState } from './types.js';
/**
 * Version-specific DISPLAY adapter for an already-verified local RecoveryView report.
 * JSON booleans are not cryptographic proof. This adapter performs no authentication,
 * materialization, file IO or effect. Caller supplies the expected scope/root/sequence.
 */
export declare function adaptRecoveryStatus(context: unknown, input: unknown): NoteState;
