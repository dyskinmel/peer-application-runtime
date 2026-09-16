/** Explicit reconnect/inquiry over the unchanged local command protocol.
 * No listener, persistence, automatic replay, ACK or shared document commit. */
import { copyData, obj, need, hex, same } from './contracts.js';
import { EventCommands, commandContext, publishCommand } from './commands.js';
import { projectEventClient } from './client-state.js';
const rejected = (operationId, code) => Object.freeze({ kind: 'rejected', operationId, code });
const unknown = (operationId) => Object.freeze({ kind: 'outcome-unknown', operationId, code: 'LOCAL_OUTCOME_UNKNOWN' });
const cancelled = (operationId) => Object.freeze({ kind: 'cancelled', operationId, phase: 'before-send' });
function signalOption(options) {
    need(options !== null && typeof options === 'object' && (Object.getPrototypeOf(options) === Object.prototype || Object.getPrototypeOf(options) === null), 'INVALID_OPTIONS');
    const keys = Reflect.ownKeys(options);
    need(keys.length === 0 || (keys.length === 1 && keys[0] === 'signal'), 'INVALID_OPTIONS');
    const d = Object.getOwnPropertyDescriptor(options, 'signal');
    need(!d || 'value' in d, 'INVALID_OPTIONS');
    const signal = d?.value;
    if (signal !== undefined)
        need(typeof signal?.aborted === 'boolean' && typeof signal?.addEventListener === 'function' && typeof signal?.removeEventListener === 'function', 'INVALID_OPTIONS');
    return signal;
}
function timeout(n) { need(typeof n === 'number' && Number.isInteger(n) && n >= 10 && n <= 60000, 'INVALID_OPTIONS'); return n; }
/** One retained operation and one active exchange per client. expectedContext is
 * pinned for life. The caller owns durable retention of the original input/ID.
 * A failed rebind leaves its candidate channel owned by the caller.
 */
export class EventCommandClient {
    #context;
    #requestTimeout;
    #cleanupTimeout;
    #used = new WeakSet();
    #cleanups = new Set();
    #binding;
    #active;
    #retained;
    #connection = 'unbound';
    #operation = Object.freeze({ kind: 'idle' });
    #known = null;
    #requiresInquiry = false;
    #cleanupFailed = false;
    #revision = 0n;
    #generation = 0n;
    constructor(expectedContext, options = {}) {
        this.#context = commandContext(expectedContext);
        let opts;
        try {
            opts = copyData(options, 1024);
            obj(opts, Object.keys(opts).filter(k => k === 'requestTimeoutMs' || k === 'cleanupTimeoutMs'));
        }
        catch {
            need(false, 'INVALID_OPTIONS');
        }
        this.#requestTimeout = timeout(opts.requestTimeoutMs ?? 6000);
        this.#cleanupTimeout = timeout(opts.cleanupTimeoutMs ?? 1000);
    }
    get current() {
        return Object.freeze({ profile: 'par-local-event-client-0041', revision: String(this.#revision), bindingGeneration: String(this.#generation),
            context: this.#context, connection: this.#connection, hostId: this.#binding?.hostId ?? null,
            operation: this.#operation, requiresInquiry: this.#requiresInquiry, knownCommit: this.#known,
            cleanup: Object.freeze({ pending: this.#cleanups.size, failed: this.#cleanupFailed }) });
    }
    get view() { return projectEventClient(this.current); }
    #touch() { this.#revision++; }
    rebind(channel, observedContext, hostId) {
        need(this.#connection !== 'closed', 'CLIENT_CLOSED');
        need(!this.#cleanupFailed, 'CLIENT_CLEANUP_FAILED');
        // At most four retired connections plus the final current connection at close.
        need(this.#cleanups.size < 4, 'CLIENT_CLEANUP_PENDING');
        need(typeof channel?.request === 'function' && typeof channel?.close === 'function', 'INVALID_PORT');
        need(!this.#used.has(channel), 'CLIENT_CHANNEL_REUSED');
        let matches = false;
        try {
            matches = same(commandContext(observedContext), this.#context);
        }
        catch { }
        need(matches, 'CLIENT_CONTEXT_MISMATCH');
        hex(hostId, 16);
        const commands = new EventCommands(channel, this.#context, hostId, { requestTimeoutMs: this.#requestTimeout });
        this.#retire('rebind-required');
        // Synchronous old cleanup failure must not consume the candidate channel.
        if (this.#cleanupFailed) {
            commands.close();
            need(false, 'CLIENT_CLEANUP_FAILED');
        }
        this.#used.add(channel);
        this.#binding = { channel, commands, hostId };
        this.#connection = 'connected';
        this.#touch();
    }
    restoreUnknown(input) {
        need(this.#connection !== 'closed', 'CLIENT_CLOSED');
        need(!this.#active, 'CLIENT_BUSY');
        need(!this.#retained, 'CLIENT_OPERATION_RETAINED');
        this.#retained = publishCommand(input, this.#context);
        this.#known = null;
        this.#requiresInquiry = true;
        this.#operation = unknown(this.#retained.operationId);
        this.#touch();
    }
    async publish(input, options = {}) {
        const retained = publishCommand(input, this.#context), id = retained.operationId, signal = signalOption(options);
        if (this.#connection === 'closed')
            return rejected(id, 'CLIENT_CLOSED');
        if (this.#active)
            return rejected(id, 'CLIENT_BUSY');
        if (this.#retained?.operationId === id && !same(this.#retained, retained))
            return rejected(id, 'CLIENT_OPERATION_CONFLICT');
        if (this.#requiresInquiry)
            return rejected(id, 'CLIENT_INQUIRY_REQUIRED');
        if (this.#cleanupFailed)
            return rejected(id, 'CLIENT_CLEANUP_FAILED');
        if (!this.#binding)
            return rejected(id, 'CLIENT_REBIND_REQUIRED');
        if (signal?.aborted)
            return cancelled(id);
        if (this.#retained?.operationId !== id)
            this.#known = null;
        this.#retained = retained;
        return await this.#perform('publish', id, signal);
    }
    async inquire(operationId, options = {}) {
        hex(operationId, 16);
        const signal = signalOption(options);
        if (this.#connection === 'closed')
            return rejected(operationId, 'CLIENT_CLOSED');
        if (this.#active)
            return rejected(operationId, 'CLIENT_BUSY');
        if (!this.#retained)
            return rejected(operationId, 'CLIENT_NO_OPERATION');
        if (this.#retained.operationId !== operationId)
            return rejected(operationId, 'CLIENT_OPERATION_MISMATCH');
        if (this.#cleanupFailed)
            return rejected(operationId, 'CLIENT_CLEANUP_FAILED');
        if (!this.#binding)
            return rejected(operationId, 'CLIENT_REBIND_REQUIRED');
        if (signal?.aborted)
            return cancelled(operationId);
        return await this.#perform('inquire', operationId, signal);
    }
    async #perform(operation, operationId, signal) {
        const binding = this.#binding;
        const abort = new AbortController(), relay = () => abort.abort();
        let linked = false;
        const unlink = () => { if (linked) {
            linked = false;
            signal?.removeEventListener('abort', relay);
        } };
        const active = { binding, operation, operationId, abort, unlink };
        this.#active = active;
        signal?.addEventListener('abort', relay, { once: true });
        linked = signal !== undefined;
        this.#operation = Object.freeze({ kind: operation === 'publish' ? 'publishing' : 'inquiring', operationId });
        this.#touch();
        try {
            const result = operation === 'publish'
                ? await binding.commands.publish(this.#retained, { signal: active.abort.signal })
                : await binding.commands.inquire(operationId, { signal: active.abort.signal });
            // Never let an older async continuation mutate the newer binding/state.
            if (this.#active !== active || this.#binding !== binding)
                return operation === 'publish' ? unknown(operationId) : rejected(operationId, 'CLIENT_SUPERSEDED');
            this.#active = undefined;
            let accepted = result;
            if (this.#known && (result.kind === 'not-found-local' || (result.kind === 'local-committed' &&
                (result.eventId !== this.#known.eventId || result.sequence !== this.#known.sequence)))) {
                accepted = rejected(operationId, 'CLIENT_OBSERVATION_CONFLICT');
                this.#requiresInquiry = true;
                this.#operation = Object.freeze({ kind: 'inquiry-failed', operationId, code: 'CLIENT_OBSERVATION_CONFLICT' });
                this.#retire('rebind-required');
            }
            else if (result.kind === 'local-committed') {
                this.#known = result;
                this.#requiresInquiry = false;
                this.#operation = result;
            }
            else if (operation === 'inquire') {
                this.#requiresInquiry = true;
                this.#operation = result.kind === 'not-found-local' ? result : Object.freeze({ kind: 'inquiry-failed', operationId, code: result.kind === 'rejected' ? result.code : 'INQUIRY_UNAVAILABLE' });
            }
            else {
                this.#requiresInquiry = result.kind === 'outcome-unknown';
                this.#operation = result;
            }
            if (binding.commands.stats().reconciliationRequired && this.#binding === binding)
                this.#retire('rebind-required');
            this.#touch();
            return accepted;
        }
        catch {
            if (this.#active !== active || this.#binding !== binding)
                return operation === 'publish' ? unknown(operationId) : rejected(operationId, 'CLIENT_SUPERSEDED');
            this.#active = undefined;
            this.#requiresInquiry = true;
            this.#operation = operation === 'publish' ? unknown(operationId) : Object.freeze({ kind: 'inquiry-failed', operationId, code: 'INQUIRY_UNAVAILABLE' });
            this.#retire('rebind-required');
            this.#touch();
            return operation === 'publish' ? unknown(operationId) : rejected(operationId, 'INQUIRY_UNAVAILABLE');
        }
        finally {
            active.unlink();
            if (this.#active === active)
                this.#active = undefined;
        }
    }
    #retire(connection) {
        const binding = this.#binding, active = this.#active;
        this.#active = undefined;
        this.#binding = undefined;
        this.#generation++;
        this.#connection = connection;
        if (active) {
            this.#requiresInquiry = true;
            this.#operation = active.operation === 'publish' ? unknown(active.operationId) : Object.freeze({ kind: 'inquiry-failed', operationId: active.operationId, code: 'CLIENT_SUPERSEDED' });
            active.unlink();
            active.abort.abort();
        }
        binding?.commands.close();
        if (binding)
            this.#release(binding.channel);
        this.#touch();
    }
    #cleanupFault() {
        if (this.#cleanupFailed)
            return;
        this.#cleanupFailed = true;
        // An unconfirmed old resource release prevents further operation admission.
        if (this.#connection !== 'closed')
            this.#retire('rebind-required');
        this.#touch();
    }
    #release(channel) {
        let completion;
        try {
            completion = channel.close();
        }
        catch {
            this.#cleanupFault();
            return;
        }
        if (completion === undefined)
            return;
        let timer;
        const deadline = new Promise(resolve => { timer = setTimeout(() => resolve(false), this.#cleanupTimeout); });
        // These handlers retain no client state if a noncooperative promise never ends.
        const disposed = Promise.resolve(completion).then(() => true, () => false);
        const tracked = Promise.race([disposed, deadline]).then(ok => { clearTimeout(timer); if (!ok)
            this.#cleanupFault(); })
            .finally(() => { this.#cleanups.delete(tracked); this.#touch(); });
        this.#cleanups.add(tracked);
        this.#touch();
    }
    /** Await bounded cleanup attempts. failed stays true on rejection or timeout;
     * pending=0 in that case is NOT proof that native resources were released. */
    async waitForCleanup() { while (this.#cleanups.size)
        await Promise.all([...this.#cleanups]); }
    close() {
        if (this.#connection === 'closed')
            return;
        this.#retire('closed');
        this.#retained = undefined;
        this.#touch();
    }
}
