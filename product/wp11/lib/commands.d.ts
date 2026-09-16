import type { Intent, NoteState } from './types.js';
/** Preflight only. The runtime MUST revalidate authority and revision at commit. */
export declare function prepareCommand(current: unknown, input: unknown): Intent;
/** Sequences are ordered only inside the same stream+scope, never revision strings. */
export declare function advanceSnapshot(previous: unknown, next: unknown): NoteState;
