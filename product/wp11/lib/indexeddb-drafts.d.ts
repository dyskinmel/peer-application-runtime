import type { DraftStoragePort } from './draft-storage.js';
export declare function openIndexedDbDraftStore(factory?: IDBFactory | undefined, name?: string): Promise<DraftStoragePort & {
    close(): void;
}>;
