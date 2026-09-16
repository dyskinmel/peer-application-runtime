import { validateDraft, validateState, scope as checkScope, scopeKey, record, string, count, check, clone, freeze, canonical } from './validate.js';
import { toScalarOffset } from './draft.js';
import { DraftError, MAX_DRAFT_ROW_BYTES, MAX_DRAFT_VERSION, validateRow, validateSlot } from './draft-storage.js';
export { DraftError } from './draft-storage.js';
const PROFILE = 'par-private-draft-aes256gcm-v1';
const INFO = new TextEncoder().encode('PAR/private-draft/key/v1');
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const hex = (a) => Array.from(a, b => b.toString(16).padStart(2, '0')).join('');
function unhex(s, length) {
    check(typeof s === 'string' && s.length % 2 === 0 && /^[0-9a-f]+$/.test(s), 'hex bytes');
    if (length !== undefined)
        check(s.length === length * 2, 'hex length');
    return Uint8Array.from(s.match(/../g), b => parseInt(b, 16));
}
function draftCopy(input) {
    if (input === null)
        return null;
    const d = validateDraft(input);
    toScalarOffset(d.text, d.selection.anchor);
    toScalarOffset(d.text, d.selection.focus);
    return d;
}
function envelope(row, slot) {
    const obj = JSON.parse(row.value);
    const e = record(obj, ['schema', 'profile', 'slot', 'version', 'operationId', 'salt', 'iv', 'ciphertext']);
    check(canonical(e) === row.value, 'canonical envelope');
    check(e.schema === 1 && e.profile === PROFILE, 'draft encryption profile');
    validateSlot(e.slot);
    if (e.slot !== slot)
        throw new DraftError('DRAFT_SCOPE_MISMATCH');
    count(e.version, MAX_DRAFT_VERSION);
    check(e.version === row.version, 'bound version');
    string(e.operationId);
    unhex(e.salt, 32);
    unhex(e.iv, 12);
    string(e.ciphertext, MAX_DRAFT_ROW_BYTES);
    check(e.ciphertext.length >= 32, 'authentication tag');
    unhex(e.ciphertext);
    return e;
}
function header(e) {
    return { schema: 1, profile: e.profile, slot: e.slot, version: e.version, operationId: e.operationId, salt: e.salt, iv: e.iv };
}
export class DraftVault {
    crypto;
    port;
    #key;
    #scope;
    #closed = false;
    constructor(crypto, port, key, scope) {
        this.crypto = crypto;
        this.port = port;
        check(key instanceof Uint8Array && key.byteLength === 32, '32 byte private draft master key');
        checkScope(scope);
        check(scope.documentId !== null, 'document required');
        check(crypto?.subtle && typeof crypto.getRandomValues === 'function', 'WebCrypto required; no downgrade');
        this.#key = new Uint8Array(key);
        this.#scope = freeze(clone(scope));
    }
    get scope() { return clone(this.#scope); }
    guard() { if (this.#closed)
        throw new DraftError('DRAFT_LOCKED'); }
    async hash(bytes) { return hex(new Uint8Array(await this.crypto.subtle.digest('SHA-256', bytes))); }
    async slot() { this.guard(); return this.hash(encoder.encode('PAR/private-draft/slot/v1\0' + scopeKey(this.#scope))); }
    async derive(salt) {
        this.guard();
        const input = await this.crypto.subtle.importKey('raw', this.#key, 'HKDF', false, ['deriveKey']);
        this.guard();
        return this.crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info: INFO }, input, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    }
    async decode(row, slot) {
        const e = envelope(row, slot);
        const k = await this.derive(unhex(e.salt, 32));
        let plain;
        try {
            plain = await this.crypto.subtle.decrypt({ name: 'AES-GCM', iv: unhex(e.iv, 12), additionalData: encoder.encode(canonical(header(e))), tagLength: 128 }, k, unhex(e.ciphertext));
        }
        catch {
            throw new DraftError('DRAFT_AUTH_FAILED');
        }
        this.guard();
        const text = decoder.decode(plain);
        const p = record(JSON.parse(text), ['scope', 'draft']);
        check(canonical(p) === text, 'canonical draft plaintext');
        checkScope(p.scope);
        if (scopeKey(p.scope) !== scopeKey(this.#scope))
            throw new DraftError('DRAFT_SCOPE_MISMATCH');
        return freeze({ version: e.version, operationId: e.operationId, draft: draftCopy(p.draft) });
    }
    async load() {
        const slot = await this.slot();
        const row = await this.port.read(slot);
        this.guard();
        return row === null ? freeze({ version: 0, operationId: null, draft: null }) : this.decode(validateRow(row), slot);
    }
    async prepare(input, expectedVersion, operationId) {
        // Copy before first await; caller mutation cannot change the in-flight save.
        this.guard();
        const draft = draftCopy(input);
        count(expectedVersion, MAX_DRAFT_VERSION - 1);
        string(operationId);
        const current = await this.load();
        this.guard();
        if (current.version !== expectedVersion)
            throw new DraftError('DRAFT_CONFLICT');
        if (current.operationId === operationId)
            throw new DraftError('OPERATION_REUSED');
        const slot = await this.slot();
        const h = { schema: 1, profile: PROFILE, slot, version: expectedVersion + 1, operationId,
            salt: hex(this.crypto.getRandomValues(new Uint8Array(32))), iv: hex(this.crypto.getRandomValues(new Uint8Array(12))) };
        const k = await this.derive(unhex(h.salt, 32));
        this.guard();
        const plain = encoder.encode(canonical({ scope: this.#scope, draft }));
        const encrypted = await this.crypto.subtle.encrypt({ name: 'AES-GCM', iv: unhex(h.iv, 12), additionalData: encoder.encode(canonical(h)), tagLength: 128 }, k, plain);
        this.guard();
        const row = validateRow({ version: h.version, value: canonical({ ...h, ciphertext: hex(new Uint8Array(encrypted)) }) });
        const body = { slot, expectedVersion, row };
        const digest = await this.hash(encoder.encode(canonical(body)));
        this.guard();
        return freeze({ ...body, digest });
    }
    async prepared(input) {
        this.guard();
        const p = record(input, ['slot', 'expectedVersion', 'row', 'digest']);
        validateSlot(p.slot);
        count(p.expectedVersion, MAX_DRAFT_VERSION - 1);
        string(p.digest, 64);
        const row = validateRow(p.row);
        check(row.version === p.expectedVersion + 1, 'version increment');
        const body = { slot: p.slot, expectedVersion: p.expectedVersion, row };
        if (await this.hash(encoder.encode(canonical(body))) !== p.digest)
            throw new DraftError('PREPARED_MISMATCH');
        if (p.slot !== await this.slot())
            throw new DraftError('DRAFT_SCOPE_MISMATCH');
        await this.decode(row, p.slot);
        return freeze({ ...body, digest: p.digest });
    }
    async receipt(p) {
        const e = envelope(p.row, p.slot);
        return freeze({ version: p.row.version, operationId: e.operationId, slot: p.slot, ciphertextHash: await this.hash(encoder.encode(p.row.value)), durability: this.port.durability, sharedSaved: false, replicated: false });
    }
    async commit(input) {
        const p = await this.prepared(input);
        const existing = await this.port.read(p.slot);
        this.guard();
        if (existing !== null && canonical(validateRow(existing)) === canonical(p.row))
            return this.receipt(p);
        if ((existing?.version ?? 0) !== p.expectedVersion)
            throw new DraftError('DRAFT_CONFLICT');
        if (existing !== null)
            await this.decode(validateRow(existing), p.slot);
        this.guard();
        try {
            await this.port.compareAndSwap(p.slot, p.expectedVersion, p.row);
        }
        catch (e) {
            if (e instanceof DraftError && e.code === 'DRAFT_CONFLICT')
                throw e;
            throw new DraftError('DRAFT_WRITE_UNKNOWN');
        }
        // Once published, a caller's lock request cannot undo persistence.
        return this.receipt(p);
    }
    async inspect(input) {
        const p = await this.prepared(input);
        const r = await this.port.read(p.slot);
        this.guard();
        if (r === null)
            return { state: 'NOT_CONFIRMED', receipt: null };
        await this.decode(validateRow(r), p.slot);
        if (canonical(r) === canonical(p.row))
            return { state: 'CONFIRMED', receipt: await this.receipt(p) };
        return { state: r.version >= p.row.version ? 'SUPERSEDED' : 'NOT_CONFIRMED', receipt: null };
    }
    close() { this.#key.fill(0); this.#closed = true; }
}
/** Explicit restore only. Persistence is not authority, a CRDT merge, or a shared commit. */
export function restoreDraft(input, current) {
    const d = draftCopy(input);
    const s = validateState(current);
    const changed = d.baseFrontier !== s.document.frontier || d.baseText !== s.document.text || s.authority.state !== 'ready' || !s.authority.sharedWriteAllowed;
    return freeze({ ...d, composing: false, requiresRebase: d.requiresRebase || changed || d.pendingRemote !== null, persisted: false });
}
