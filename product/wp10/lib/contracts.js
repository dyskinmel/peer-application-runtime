export class EventBindingError extends Error {
    code;
    constructor(code) {
        super(code);
        this.code = code;
        this.name = 'EventBindingError';
    }
}
export const fail = (code = 'PORT_INVALID') => { throw new EventBindingError(code); };
export function need(ok, code = 'PORT_INVALID') { if (!ok)
    fail(code); }
export const u64 = (v) => {
    need(typeof v === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(v));
    const n = BigInt(v);
    need(n <= 18446744073709551615n);
    return n;
};
export const i64 = (v) => {
    need(typeof v === 'string' && /^(0|-?[1-9][0-9]{0,18}|-?[1-9][0-9]{19})$/.test(v));
    const n = BigInt(v);
    need(n >= -9223372036854775808n && n <= 9223372036854775807n);
    return n;
};
export function hex(v, bytes, maxBytes = 4096) {
    need(typeof v === 'string' && v.length <= maxBytes * 2 && v.length % 2 === 0 && /^[0-9a-f]*$/.test(v));
    need(bytes === undefined ? v.length > 0 : v.length === bytes * 2);
    return v;
}
/** Reject accessors/custom prototypes before traversal. Not a JS Proxy sandbox. */
export function copyData(value, maxBytes = 1500000) {
    let nodes = 0, bytes = 0;
    const stack = new Set();
    const visit = (v, depth) => {
        need(++nodes <= 12000 && depth <= 10);
        if (v === null || typeof v === 'boolean')
            return v;
        if (typeof v === 'string') {
            bytes += new TextEncoder().encode(v).length;
            need(bytes <= maxBytes);
            need(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(v));
            return v;
        }
        if (typeof v === 'number') {
            need(Number.isSafeInteger(v));
            return v;
        }
        need(typeof v === 'object' && v !== null && !stack.has(v));
        stack.add(v);
        const arr = Array.isArray(v), proto = Object.getPrototypeOf(v);
        need(arr ? proto === Array.prototype : (proto === Object.prototype || proto === null));
        const keys = Reflect.ownKeys(v);
        need(keys.length <= 4096);
        const out = arr ? [] : Object.create(null);
        if (arr) {
            need(v.length <= 4096);
            need(keys.length === v.length + 1);
        }
        for (const key of keys) {
            need(typeof key === 'string');
            const d = Object.getOwnPropertyDescriptor(v, key);
            need(d && 'value' in d);
            if (arr && key === 'length')
                continue;
            need(d.enumerable);
            if (arr)
                need(/^(0|[1-9][0-9]*)$/.test(key) && Number(key) < v.length);
            bytes += key.length;
            need(bytes <= maxBytes);
            Object.defineProperty(out, key, { value: visit(d.value, depth + 1), enumerable: true, writable: true, configurable: true });
        }
        stack.delete(v);
        return out;
    };
    return visit(value, 0);
}
export function obj(v, keys) {
    need(typeof v === 'object' && v !== null && !Array.isArray(v));
    const r = v;
    need(Object.keys(r).sort().join('|') === [...keys].sort().join('|'));
    return r;
}
export function same(a, b) {
    const normalize = (v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, normalize(v[k])])) : Array.isArray(v) ? v.map(normalize) : v;
    return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}
export function cursor(v) {
    const r = obj(v, ['position', 'revision', 'eventId', 'token']);
    const p = u64(r.position);
    u64(r.revision);
    need(p === 0n ? r.eventId === null : typeof r.eventId === 'string');
    if (r.eventId !== null)
        hex(r.eventId, 32);
    return Object.freeze({ position: r.position, revision: r.revision, eventId: r.eventId, token: hex(r.token) });
}
export function context(v) {
    const r = obj(copyData(v, 16384), ['protocol', 'appId', 'spaceId', 'streamId', 'epoch', 'schema', 'schemaDigest', 'issuer', 'consumerId', 'journalGeneration']);
    need(r.protocol === 'par-sdk-events-local-0038');
    need(typeof r.appId === 'string' && /^[a-z0-9][a-z0-9.-]{0,127}$/.test(r.appId));
    for (const k of ['spaceId', 'streamId', 'schemaDigest', 'issuer', 'journalGeneration'])
        hex(r[k], 32);
    hex(r.consumerId, 16);
    need(u64(r.epoch) > 0n);
    need(typeof r.schema === 'object' && r.schema !== null && !Array.isArray(r.schema));
    const schema = r.schema, keys = Object.keys(schema);
    need(keys.length >= 1 && keys.length <= 16);
    for (const k of keys)
        need(/^[a-z][a-z0-9_]{0,31}$/.test(k) && ['text', 'uint64', 'int64', 'bool', 'bytes'].includes(schema[k]));
    Object.freeze(schema);
    return Object.freeze(r);
}
export function response(v, expected, session, kind, keys) {
    const r = obj(copyData(v), ['kind', 'context', 'sessionId', ...keys]);
    need(r.kind === kind && same(context(r.context), expected));
    hex(r.sessionId, 16);
    if (session !== undefined)
        need(r.sessionId === session);
    return r;
}
export function payload(v, schema) {
    const r = obj(v, Object.keys(schema)), out = Object.create(null);
    let raw = 0;
    for (const key of Object.keys(schema)) {
        const f = obj(r[key], ['kind', 'value']);
        need(f.kind === schema[key]);
        const val = f.value;
        switch (f.kind) {
            case 'uint64':
                out[key] = u64(val);
                break;
            case 'int64':
                out[key] = i64(val);
                break;
            case 'bool':
                need(typeof val === 'boolean');
                out[key] = val;
                break;
            case 'text':
                need(typeof val === 'string');
                raw += new TextEncoder().encode(val).length;
                out[key] = val;
                break;
            case 'bytes':
                need(typeof val === 'string' && val.length <= 32768 && val.length % 2 === 0 && /^[0-9a-f]*$/.test(val));
                raw += val.length / 2;
                out[key] = Object.freeze({ hex: val });
                break;
            default: fail();
        }
    }
    need(raw <= 16384);
    return { value: Object.freeze(out), rawMaterialBytes: raw };
}
