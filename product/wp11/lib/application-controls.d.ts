/** Optional status/controls panel. All writes and network effects require explicit actions. */
import { ApplicationEmbedding } from './application-embedding.js';
export interface ApplicationControls {
    setLocale(locale: 'ja' | 'en'): void;
    destroy(): void;
    cleanup(): Promise<void>;
}
export declare function mountApplicationControls(root: HTMLElement, embedding: ApplicationEmbedding, initialLocale?: 'ja' | 'en'): ApplicationControls;
