import type { NoteState, NoteViewModel, CommandKind, Message, Preview } from './types.js';
export declare function matchingPreview(s: NoteState, kind: CommandKind): Preview | undefined;
export declare function sharedWriteEligible(s: NoteState): boolean;
export declare function present(input: unknown): NoteViewModel;
/** Return only changed status messages, never body edits, focus moves or timers. */
export declare function announcements(previous: NoteViewModel, current: NoteViewModel): readonly Message[];
