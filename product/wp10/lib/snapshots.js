import { EventBindingError, need, u64 } from './contracts.js';
/** Capacity one; volatile state notifications, never a durable event stream. */
export class LatestSnapshots {
    #max;
    #revision;
    #payload;
    #delivered;
    #closed = false;
    #waiter;
    constructor(options = {}) { this.#max = options.maxBytes ?? 65536; need(Number.isInteger(this.#max) && this.#max >= 1 && this.#max <= 524288, 'INVALID_OPTIONS'); }
    publish(revision, payload) {
        need(!this.#closed, 'CLOSED');
        const n = u64(revision);
        need(payload instanceof Uint8Array, 'INVALID_PAYLOAD');
        need(payload.byteLength <= this.#max, 'RESOURCE_LIMIT');
        if (this.#revision !== undefined) {
            need(n >= this.#revision, 'REVISION_ROLLBACK');
            if (n === this.#revision) {
                need(payload.length === this.#payload.length && payload.every((b, i) => b === this.#payload[i]), 'REVISION_CONFLICT');
                return;
            }
        }
        this.#revision = n;
        this.#payload = new Uint8Array(payload);
        if (this.#waiter) {
            const resolve = this.#waiter;
            this.#waiter = undefined;
            resolve(this.#take());
        }
    }
    #take() { this.#delivered = this.#revision; return { done: false, value: Object.freeze({ revision: this.#revision, payload: new Uint8Array(this.#payload) }) }; }
    [Symbol.asyncIterator]() { return this; }
    async next() {
        if (this.#closed)
            return { done: true, value: undefined };
        need(!this.#waiter, 'BUSY');
        if (this.#revision !== undefined && this.#revision !== this.#delivered)
            return this.#take();
        return new Promise(resolve => { this.#waiter = resolve; });
    }
    async return() {
        this.#closed = true;
        this.#payload = undefined;
        const resolve = this.#waiter;
        this.#waiter = undefined;
        const result = { done: true, value: undefined };
        resolve?.(result);
        return result;
    }
    async throw(error) { await this.return(); throw error ?? new EventBindingError('CANCELLED'); }
}
