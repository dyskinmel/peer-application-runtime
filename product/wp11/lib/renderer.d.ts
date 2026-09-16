/** A semantic renderer over the existing Presenter. Stable editor DOM; no implicit domain effects. */
import type { NoteState, Draft, Intent } from './types.js';
import type { FetchOwnerClient } from './fetch-owner.js';
import type { ApplicationEmbedding } from './application-embedding.js';
import type { DraftSessionPort } from './draft-session.js';
export interface RendererOptions {
    locale?: 'ja' | 'en';
    draftSession?: DraftSessionPort;
    /** Borrowed owner port; mounting never fetches or mutates the edit buffer. */
    fetchOwner?: FetchOwnerClient;
    /** Single-screen lifetime lease. Destroy closes only the connection; persistent records remain. */
    applicationEmbedding?: ApplicationEmbedding;
    effectPort?: (intent: Intent) => Promise<{
        outcome: 'accepted' | 'unknown' | 'unavailable';
    } | {
        outcome: 'observed';
        observation: NoteState;
    }>;
}
export interface ReferenceView {
    update(next: unknown): void;
    getDraft(): Draft;
    setLocale(locale: 'ja' | 'en'): void;
    attachDraftSession(session: DraftSessionPort): Promise<void>;
    destroy(): void;
    applicationCleanup(): Promise<void>;
}
export declare function mountReference(root: HTMLElement, input: unknown, options?: RendererOptions): ReferenceView;
