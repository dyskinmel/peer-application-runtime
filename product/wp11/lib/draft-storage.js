/** Storage boundary for private, local drafts. Never a replication receipt. */
import { record, check, count, string, clone, freeze, canonical } from './validate.js';
export const MAX_DRAFT_ROW_BYTES = 10 * 1024 * 1024;
export const MAX_DRAFT_VERSION = 1_000_000_000;
export class DraftError extends Error {
    code;
    constructor(code) {
        super(code);
        this.code = code;
        this.name = 'DraftError';
    }
}
export function validateSlot(slot) {
    check(typeof slot === 'string' && /^[0-9a-f]{64}$/.test(slot), 'opaque draft slot');
}
export function validateRow(input) {
    const r = record(input, ['version', 'value']);
    count(r.version, MAX_DRAFT_VERSION);
    check(r.version > 0, 'positive draft version');
    string(r.value, MAX_DRAFT_ROW_BYTES);
    return freeze(clone(r));
}
export function parseRow(text) {
    string(text, MAX_DRAFT_ROW_BYTES + 1024);
    const parsed = JSON.parse(text);
    check(canonical(parsed) === text, 'canonical row (no duplicate fields)');
    return validateRow(parsed);
}
