/** Portable copy of the WP10 descriptor-only JSON reader; same node/depth/byte budgets.
 * Kept local so a standalone Presenter build does not import a sibling SDK path. */
import { check } from './validate.js';
function need(value) { check(value, 'owner data'); }
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
