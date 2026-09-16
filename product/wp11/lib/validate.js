import { COMMANDS } from './types.js';
export class ContractError extends Error {
    code;
    detail;
    constructor(code, detail = '') {
        super(`${code}${detail ? ': ' + detail : ''}`);
        this.code = code;
        this.detail = detail;
        this.name = 'ContractError';
    }
}
export function check(ok, detail, code = 'INVALID_INPUT') { if (!ok)
    throw new ContractError(code, detail); }
export function record(v, keys) {
    check(v !== null && typeof v === 'object' && !Array.isArray(v), 'object');
    check(Object.getPrototypeOf(v) === Object.prototype || Object.getPrototypeOf(v) === null, 'plain object');
    const descriptors = Object.getOwnPropertyDescriptors(v);
    check(Reflect.ownKeys(v).length === keys.length && keys.every(k => Object.hasOwn(descriptors, k)), 'exact fields');
    for (const k of keys) {
        const d = descriptors[k];
        check(d && 'value' in d && d.enumerable, 'data properties only');
    }
    return v;
}
export function string(v, max = 256, min = 1) {
    check(typeof v === 'string' && v.length >= min && v.length <= max, 'string bound');
    for (let i = 0; i < v.length; i++) {
        const c = v.charCodeAt(i);
        if (c >= 0xd800 && c <= 0xdbff) {
            const n = v.charCodeAt(++i);
            check(n >= 0xdc00 && n <= 0xdfff, 'unpaired surrogate');
        }
        else
            check(c < 0xdc00 || c > 0xdfff, 'unpaired surrogate');
    }
    check(new TextEncoder().encode(v).byteLength <= max, 'utf8 bound');
}
export function enumValue(v, vs) { check(vs.includes(v), 'enum'); }
export function count(v, max = 65536) { check(typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= max, 'integer bound'); }
export function u64(v) { check(typeof v === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(v) && BigInt(v) <= 18446744073709551615n, 'u64 decimal'); }
export function bool(v) { check(typeof v === 'boolean', 'boolean'); }
export function list(v, max, fn) { check(Array.isArray(v) && v.length <= max, 'array bound'); check(Object.getPrototypeOf(v) === Array.prototype, 'plain array'); check(Reflect.ownKeys(v).length === v.length + 1, 'exact array fields'); for (let i = 0; i < v.length; i++) {
    const d = Object.getOwnPropertyDescriptor(v, String(i));
    check(d && 'value' in d && d.enumerable, 'array data');
    fn(d.value);
} }
function optionalId(v) { if (v !== null)
    string(v); }
function timestamp(v) { string(v, 24); check(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(v), 'UTC timestamp'); const t = new Date(v); check(Number.isFinite(t.getTime()) && t.toISOString() === v, 'valid date'); }
const STORAGE = ['native-tested', 'native-candidate', 'browser-best-effort'];
const KEYS = ['available', 'missing', 'unknown'];
export function scope(v) { const x = record(v, ['appId', 'spaceId', 'documentId']); string(x.appId); string(x.spaceId); optionalId(x.documentId); }
export function scopeKey(v) { return JSON.stringify([v.appId, v.spaceId, v.documentId]); }
export function previewValue(v) { const x = record(v, ['kind', 'revision', 'scopeKey', 'target', 'planDigest', 'impact']); enumValue(x.kind, COMMANDS); string(x.revision); string(x.scopeKey, 2048); string(x.target); string(x.planDigest, 64); check(/^[0-9a-f]{64}$/.test(x.planDigest), 'digest'); string(x.impact, 4096); }
export function freeze(v) { if (v && typeof v === 'object') {
    for (const x of Object.values(v))
        freeze(x);
    Object.freeze(v);
} return v; }
export function clone(v) { return JSON.parse(JSON.stringify(v)); }
/** Stable comparison for validated JSON. Not a signature, hash or authorization token. */
export function canonical(v) { if (Array.isArray(v))
    return '[' + v.map(canonical).join(',') + ']'; if (v && typeof v === 'object')
    return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}'; return JSON.stringify(v); }
export function validateState(v) {
    const s = record(v, ['schemaVersion', 'streamId', 'sequence', 'revision', 'snapshotTime', 'scope', 'surface', 'capabilities', 'supportedCommands', 'local', 'protection', 'connection', 'authority', 'document', 'recovery', 'rpc', 'invite', 'contribution', 'presence', 'diagnostic', 'previews', 'evidence']);
    check(s.schemaVersion === 1, 'schema');
    string(s.streamId);
    u64(s.sequence);
    string(s.revision);
    timestamp(s.snapshotTime);
    scope(s.scope);
    enumValue(s.surface, ['workspace', 'protection', 'invite', 'editor', 'recovery', 'contribution', 'diagnostics', 'connectivity', 'rpc', 'browser', 'presence']);
    const cap = record(s.capabilities, ['host', 'storageClass', 'durableKeeperEligible', 'keyProtection', 'supportsLocalEffectTransaction', 'background']);
    enumValue(cap.host, ['linux', 'macos', 'windows', 'ios', 'android', 'browser']);
    enumValue(cap.storageClass, STORAGE);
    bool(cap.durableKeeperEligible);
    bool(cap.supportsLocalEffectTransaction);
    enumValue(cap.keyProtection, ['software-encrypted', 'os-protected', 'hardware-wrapped', 'hardware-nonexportable']);
    enumValue(cap.background, ['unsupported', 'os-scheduled', 'persistent-process']);
    list(s.supportedCommands, COMMANDS.length, x => enumValue(x, COMMANDS));
    check(new Set(s.supportedCommands).size === s.supportedCommands.length, 'duplicate commands');
    const loc = record(s.local, ['state', 'storageClass', 'operationId', 'cancellationRequested']);
    enumValue(loc.state, ['committed', 'pending', 'failed', 'unknown']);
    enumValue(loc.storageClass, STORAGE);
    optionalId(loc.operationId);
    bool(loc.cancellationRequested);
    check(loc.storageClass === cap.storageClass, 'storage class mismatch');
    const p = record(s.protection, ['root', 'goal', 'observations', 'keys', 'physicalIndependence']);
    string(p.root);
    count(p.goal, 256);
    enumValue(p.keys, KEYS);
    enumValue(p.physicalIndependence, ['unknown', 'declared']);
    const ids = new Set();
    list(p.observations, 256, v => { const o = record(v, ['deviceId', 'manifest', 'byteComplete', 'semanticClosure', 'freshness', 'storageClass', 'reachable', 'observedAt']); string(o.deviceId); string(o.manifest); bool(o.byteComplete); enumValue(o.semanticClosure, ['verified', 'unknown', 'incomplete']); enumValue(o.freshness, ['fresh', 'stale', 'unknown']); enumValue(o.storageClass, STORAGE); enumValue(o.reachable, ['observed', 'not-observed', 'unknown']); timestamp(o.observedAt); check(!ids.has(o.deviceId), 'duplicate device observation'); ids.add(o.deviceId); });
    const c = record(s.connection, ['state', 'peers']);
    enumValue(c.state, ['offline', 'connecting', 'connected', 'relay-required', 'unknown']);
    count(c.peers, 256);
    check(c.state !== 'connected' || c.peers > 0, 'connected without peer');
    const a = record(s.authority, ['state', 'controlHead', 'epoch', 'role', 'sharedWriteAllowed']);
    enumValue(a.state, ['ready', 'pending', 'fork', 'denied', 'rebase-required', 'seed-pending']);
    string(a.controlHead);
    u64(a.epoch);
    enumValue(a.role, ['owner', 'editor', 'reader', 'none']);
    bool(a.sharedWriteAllowed);
    check(!a.sharedWriteAllowed || (a.state === 'ready' && ['owner', 'editor'].includes(a.role)), 'inconsistent write authority');
    const d = record(s.document, ['read', 'title', 'text', 'frontier', 'innerValidated', 'applied', 'conflicts', 'privateDraft', 'knownCatalogComplete', 'missingObjects']);
    enumValue(d.read, ['found', 'absent-local', 'waiting-data', 'tombstoned', 'quarantined']);
    string(d.title, 1024, 0);
    string(d.text, 1048576, 0);
    string(d.frontier);
    bool(d.innerValidated);
    bool(d.applied);
    bool(d.privateDraft);
    bool(d.knownCatalogComplete);
    u64(d.missingObjects);
    list(d.conflicts, 32, v => { const c = record(v, ['value', 'provenance']); string(c.value, 65536, 0); string(c.provenance, 1024); });
    check(!d.applied || (d.innerValidated && d.read === 'found'), 'application requires validation');
    const r = record(s.recovery, ['phase', 'received', 'total', 'recipientValidated', 'keys', 'missingObjects']);
    enumValue(r.phase, ['idle', 'obtaining-keys', 'fetching', 'verifying', 'review', 'read-only', 'partial']);
    u64(r.received);
    if (r.total !== null) {
        u64(r.total);
        check(BigInt(r.received) <= BigInt(r.total), 'progress over total');
    }
    bool(r.recipientValidated);
    enumValue(r.keys, KEYS);
    u64(r.missingObjects);
    check(!r.recipientValidated || (r.keys === 'available' && r.missingObjects === '0'), 'invalid recipient completion');
    const rpc = record(s.rpc, ['state', 'operationId']);
    enumValue(rpc.state, ['idle', 'pending', 'unknown', 'completed']);
    optionalId(rpc.operationId);
    check(rpc.state === 'idle' || rpc.operationId !== null, 'missing operation');
    const inv = record(s.invite, ['phase', 'role', 'targetDevice', 'manualAvailable', 'fileAvailable']);
    enumValue(inv.phase, ['none', 'pending', 'review', 'stale']);
    enumValue(inv.role, ['reader', 'editor', 'opaque-keeper']);
    optionalId(inv.targetDevice);
    bool(inv.manualAvailable);
    bool(inv.fileAvailable);
    check(inv.phase !== 'review' || inv.targetDevice !== null, 'missing invite target');
    const con = record(s.contribution, ['state', 'storageBudget', 'relayBudget', 'activeLeases']);
    enumValue(con.state, ['disabled', 'review-stop', 'enabled']);
    u64(con.storageBudget);
    u64(con.relayBudget);
    count(con.activeLeases, 65536);
    check(con.state !== 'disabled' || (con.storageBudget === '0' && con.relayBudget === '0'), 'disabled contribution budget');
    enumValue(s.presence, ['recent', 'unknown']);
    enumValue(s.diagnostic, [null, 'storage-full']);
    list(s.previews, COMMANDS.length, previewValue);
    check(new Set(s.previews.map(v => v.kind)).size === s.previews.length, 'duplicate preview');
    const e = record(s.evidence, ['kind', 'references']);
    enumValue(e.kind, ['synthetic', 'runtime-observation']);
    list(e.references, 32, v => string(v, 2048));
    return freeze(clone(s));
}
export function validateCommand(v) { const c = record(v, ['schemaVersion', 'kind', 'expectedRevision', 'streamId', 'sequence', 'scope', 'operationId', 'confirmation']); check(c.schemaVersion === 1, 'command schema'); enumValue(c.kind, COMMANDS); string(c.expectedRevision); string(c.streamId); u64(c.sequence); scope(c.scope); string(c.operationId); if (c.confirmation !== null)
    previewValue(c.confirmation); return freeze(clone(c)); }
export function validateDraft(v) {
    const d = record(v, ['schemaVersion', 'text', 'baseText', 'baseFrontier', 'selection', 'composing', 'dirty', 'requiresRebase', 'persisted', 'pendingRemote', 'lastRemote']);
    check(d.schemaVersion === 1 && d.persisted === false, 'draft schema');
    string(d.text, 1048576, 0);
    string(d.baseText, 1048576, 0);
    string(d.baseFrontier);
    bool(d.composing);
    bool(d.dirty);
    bool(d.requiresRebase);
    const s = record(d.selection, ['anchor', 'focus']);
    count(s.anchor, 1048576);
    count(s.focus, 1048576);
    check(s.anchor <= d.text.length && s.focus <= d.text.length, 'selection bound');
    for (const f of ['pendingRemote', 'lastRemote'])
        if (d[f] !== null) {
            const r = record(d[f], ['text', 'frontier', 'sequence']);
            string(r.text, 1048576, 0);
            string(r.frontier);
            u64(r.sequence);
        }
    check(d.dirty === (d.text !== d.baseText), 'draft dirty mismatch');
    return clone(d);
}
export function validateDraftEvent(v) {
    check(v && typeof v === 'object', 'draft event');
    const desc = Object.getOwnPropertyDescriptor(v, 'type');
    check(desc && 'value' in desc, 'event type');
    const type = desc.value;
    enumValue(type, ['composition-start', 'composition-end', 'input', 'remote', 'accept-remote', 'authority-changed']);
    if (type === 'input') {
        const e = record(v, ['type', 'text', 'anchor', 'focus']);
        string(e.text, 1048576, 0);
        count(e.anchor, 1048576);
        count(e.focus, 1048576);
    }
    else if (type === 'remote') {
        const e = record(v, ['type', 'text', 'frontier', 'sequence']);
        string(e.text, 1048576, 0);
        string(e.frontier);
        u64(e.sequence);
    }
    else
        record(v, ['type']);
    return v;
}
