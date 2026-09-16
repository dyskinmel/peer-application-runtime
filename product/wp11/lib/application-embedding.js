/** Lifetime owner for one experimental application connection and durable caller slot.
 * No connection factory, file path or implicit replay is exposed to the renderer.
 * Stores/ports are trusted cooperative providers, not sandboxed code.
 */
import { ApplicationOwnerClient, applicationOwnerKey, validateApplicationContext, validateOriginalApplication } from './application-owner.js';
import { check, record, canonical, freeze, count, list, ContractError } from './validate.js';
const errorCode = (e) => {
    const c = e && typeof e === 'object' ? Object.getOwnPropertyDescriptor(e, 'code')?.value : null;
    return typeof c === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(c) ? c : 'APPLICATION_EMBEDDING_FAILED';
};
export class ApplicationEmbedding {
    store;
    context;
    targets;
    localExperiment;
    key;
    trackedStore;
    client = null;
    lifecycle = 'DETACHED';
    caller = 'UNLOADED';
    original = null;
    attempted = false;
    inquiry = false;
    why = null;
    busy = false;
    epoch = 0;
    invalidated = false;
    cancelled = false;
    storePending = 0;
    requestsPending = 0;
    actionPending = 0;
    closing = null;
    portClosed = false;
    portCloseFailed = false;
    viewOwned = false;
    listeners = new Set();
    constructor(context, store, values, options = {}) {
        this.store = store;
        this.context = validateApplicationContext(context);
        this.key = applicationOwnerKey(this.context);
        check(store && typeof store.load === 'function' && typeof store.save === 'function' && typeof store.markDispatch === 'function', 'store', 'CALLER_STORE_REQUIRED');
        list(values, 64, v => check(typeof v === 'string' && /^[0-9a-f]{64}$/.test(v), 'target'));
        check(values.length > 0 && new Set(values).size === values.length, 'targets');
        this.targets = freeze([...values].sort());
        const o = record(options, Object.keys(options));
        check(Object.keys(o).every(k => k === 'localExperiment'), 'options');
        check(o.localExperiment === undefined || typeof o.localExperiment === 'boolean', 'experiment');
        this.localExperiment = o.localExperiment === true;
        // Validate every provider read, including the second read inside client.restore.
        this.trackedStore = { load: () => this.trackStore(async () => this.readRecord(await this.store.load())), save: v => this.trackStore(() => this.store.save(v)), markDispatch: id => this.trackStore(() => this.store.markDispatch(id)) };
    }
    async trackStore(f) { this.storePending++; try {
        return await f();
    }
    finally {
        this.storePending--;
    } }
    remember() {
        const c = this.client?.current;
        if (!c)
            return;
        if (c.original !== null)
            this.original = c.original;
        this.attempted = this.attempted || c.dispatchAttempted;
        this.inquiry = this.inquiry || c.needsInquiry;
    }
    get current() {
        this.remember();
        const c = this.client?.current;
        return freeze({ lifecycle: this.lifecycle, caller: this.caller, original: this.original, dispatchAttempted: this.attempted,
            snapshot: this.lifecycle === 'ATTACHED' && !this.busy && this.why === null && c?.status === 'CURRENT' ? c.snapshot : null,
            busy: this.busy, needsInquiry: this.inquiry || !!c?.needsInquiry, reason: this.why ?? c?.reason ?? null,
            localExperiment: this.localExperiment, pendingStore: this.storePending, pendingRequests: this.requestsPending });
    }
    subscribe(fn) {
        check(typeof fn === 'function' && this.listeners.size < 8, 'subscriber', 'APPLICATION_SUBSCRIBER_LIMIT');
        this.listeners.add(fn);
        return () => { this.listeners.delete(fn); };
    }
    notify() { for (const fn of this.listeners) {
        try {
            fn();
        }
        catch { /* Presentation callbacks cannot turn a completed operation into a failure. */ }
    } }
    assertViewAvailable() { check(!this.viewOwned, 'one screen', 'APPLICATION_VIEW_OWNED'); }
    acquireView() {
        check(!this.viewOwned, 'one screen', 'APPLICATION_VIEW_OWNED');
        this.viewOwned = true;
        let active = true;
        return () => { if (active) {
            active = false;
            this.viewOwned = false;
        } };
    }
    /** Takes ownership only on success. Failed attachment leaves the supplied port with its caller. */
    attach(context, port) {
        check(!this.invalidated, 'invalidated', 'APPLICATION_CONTEXT_CHANGED');
        check(this.lifecycle === 'DETACHED' && this.actionPending === 0 && this.storePending === 0 && this.requestsPending === 0, 'owned', 'APPLICATION_CONNECTION_OWNED');
        const c = validateApplicationContext(context);
        check(applicationOwnerKey(c) === this.key, 'stable owner', 'APPLICATION_CONTEXT_MISMATCH');
        check(port && typeof port.request === 'function' && typeof port.close === 'function', 'port');
        this.portClosed = false;
        this.portCloseFailed = false;
        this.closing = null;
        let closePromise = null;
        const tracked = {
            request: async (...args) => { this.requestsPending++; try {
                return await port.request(...args);
            }
            finally {
                this.requestsPending--;
            } },
            close: () => {
                if (closePromise === null) {
                    closePromise = Promise.resolve().then(() => port.close()).then(() => { this.portClosed = true; }, e => { this.portCloseFailed = true; throw e; });
                }
                return closePromise;
            }
        };
        this.client = new ApplicationOwnerClient(c, tracked, this.trackedStore);
        this.caller = 'UNLOADED';
        this.why = null;
        this.lifecycle = 'ATTACHED';
        this.epoch++;
        this.notify();
    }
    idle() {
        check(!this.invalidated, 'invalidated', 'APPLICATION_CONTEXT_CHANGED');
        check(this.lifecycle === 'ATTACHED' && this.client !== null, 'attach first', 'APPLICATION_ATTACH_REQUIRED');
        check(!this.busy, 'busy', 'APPLICATION_EMBEDDING_BUSY');
        return this.client;
    }
    async run(f) {
        const client = this.idle(), at = this.epoch;
        this.busy = true;
        this.actionPending++;
        this.why = null;
        this.cancelled = false;
        this.notify();
        const active = () => { check(at === this.epoch && this.lifecycle === 'ATTACHED' && !this.invalidated, 'detached', 'APPLICATION_STALE_RESPONSE'); check(!this.cancelled, 'cancelled', 'CANCELLED'); };
        try {
            active();
            const value = await f(client, active);
            active();
            this.remember();
            this.inquiry = client.current.needsInquiry;
            return value;
        }
        catch (e) {
            this.remember();
            if (at === this.epoch)
                this.why = errorCode(e);
            throw e;
        }
        finally {
            this.actionPending--;
            this.busy = false;
            this.notify();
        }
    }
    readRecord(raw) {
        if (raw === null) {
            check(this.original === null && !this.attempted, 'known record missing', 'CALLER_INTENT_MISSING');
            return null;
        }
        const r = record(raw, ['original', 'dispatchAttempted']);
        const original = validateOriginalApplication(r.original);
        check(original.ownerKey === this.key && canonical(original.targets) === canonical(this.targets), 'caller context', 'CALLER_CONTEXT_MISMATCH');
        check(typeof r.dispatchAttempted === 'boolean', 'marker');
        if (this.original)
            check(canonical(original) === canonical(this.original), 'original changed', 'CALLER_INTENT_CONFLICT');
        check(!this.attempted || r.dispatchAttempted, 'known marker missing', 'CALLER_MARKER_MISSING');
        return freeze({ original, dispatchAttempted: r.dispatchAttempted });
    }
    /** Read only; never creates a record, connection, intent or dispatch marker. */
    async restore() {
        return this.run(async (c, active) => {
            try {
                const r = this.readRecord(await this.trackedStore.load());
                active();
                if (r === null) {
                    this.caller = 'EMPTY';
                    return;
                }
                this.original = r.original;
                this.attempted = this.attempted || r.dispatchAttempted;
                this.inquiry = true;
                await c.restore();
                active();
                this.caller = 'SAVED';
            }
            catch (e) {
                this.caller = 'UNCERTAIN';
                throw e;
            }
        });
    }
    /** Separate explicit local action. The UI never invents or replaces an ID. */
    async stage(operationId, expectedRevision) {
        this.idle();
        check(this.localExperiment, 'explicit experiment', 'APPLICATION_EXPERIMENT_REQUIRED');
        count(expectedRevision, 63);
        const original = validateOriginalApplication({ profile: 'par-caller-application-0052', ownerKey: this.key, operationId, expectedRevision, targets: this.targets });
        check(!this.attempted, 'marker recorded', 'INQUIRY_REQUIRED');
        if (this.original)
            check(canonical(original) === canonical(this.original), 'different ID', 'ORIGINAL_OPERATION_REQUIRED');
        return this.run(async (c, active) => {
            try {
                const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(this.targets)));
                active();
                const sha = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
                check(sha === this.context.document.targetDigest, 'targets', 'APPLICATION_TARGETS');
                const prior = this.readRecord(await this.trackedStore.load());
                active();
                if (prior) {
                    check(canonical(prior.original) === canonical(original), 'slot conflict', 'CALLER_INTENT_CONFLICT');
                    check(!prior.dispatchAttempted, 'marker', 'INQUIRY_REQUIRED');
                }
                this.original = original;
                this.inquiry = true;
                this.caller = 'UNCERTAIN';
                await this.trackedStore.save(original);
                active();
                const stored = this.readRecord(await this.trackedStore.load());
                active();
                check(stored !== null && !stored.dispatchAttempted, 'save readback', 'CALLER_STORE_UNCERTAIN');
                await c.restore();
                active();
                this.caller = 'SAVED';
            }
            catch (e) {
                this.caller = 'UNCERTAIN';
                throw e;
            }
        });
    }
    can(op) {
        const s = this.current;
        if (s.lifecycle !== 'ATTACHED' || s.busy || this.invalidated)
            return false;
        if (op === 'restore' || op === 'observe')
            return true;
        if (op === 'stage')
            return this.localExperiment && !s.dispatchAttempted && s.original === null;
        if (s.caller !== 'SAVED' || s.original === null || !s.snapshot)
            return false;
        if (!s.snapshot.operations.includes(op))
            return false;
        if (op === 'inquire')
            return true;
        if (!this.localExperiment || s.snapshot.capability !== 'LOCAL_EXPERIMENT')
            return false;
        if (op === 'prepare')
            return !s.dispatchAttempted && ['EMPTY', 'PREPARED'].includes(s.snapshot.journal.state);
        if (op === 'dispatch')
            return !s.dispatchAttempted && !s.needsInquiry && s.snapshot.journal.state === 'PREPARED';
        if (op === 'retire')
            return s.snapshot.journal.state === 'OBSERVED';
        return !s.dispatchAttempted && s.snapshot.journal.state === 'PREPARED';
    }
    observe(options = {}) { return this.run(c => c.observe(options)); }
    prepare(options = {}) {
        return this.run((c) => { check(this.localExperiment, 'experiment', 'APPLICATION_EXPERIMENT_REQUIRED'); check(this.caller === 'SAVED' && this.original !== null, 'stage first', 'CALLER_INTENT_REQUIRED'); const i = this.original; return c.prepare(i.operationId, i.expectedRevision, i.targets, options); });
    }
    action(op, options) {
        return this.run(c => { if (op !== 'inquire')
            check(this.localExperiment, 'experiment', 'APPLICATION_EXPERIMENT_REQUIRED'); check(this.caller === 'SAVED', 'restore first', 'CALLER_INTENT_REQUIRED'); return c[op](options); });
    }
    dispatch(o = {}) { return this.action('dispatch', o); }
    inquire(o = {}) { return this.action('inquire', o); }
    retire(o = {}) { return this.action('retire', o); }
    abandon(o = {}) { return this.action('abandon', o); }
    cancel() { if (this.busy)
        this.cancelled = true; this.client?.cancel(); }
    /** Authority changes require a separately reviewed binding; no automatic migration. */
    invalidate() { this.invalidated = true; this.why = 'APPLICATION_CONTEXT_CHANGED'; return this.detach(); }
    /** The retained close promise is not retried after a failure. No persistent record is removed. */
    detach() {
        if (this.closing !== null)
            return this.closing;
        if (this.lifecycle === 'DETACHED')
            return Promise.resolve();
        this.remember();
        this.lifecycle = 'DETACHING';
        this.epoch++;
        this.client?.cancel();
        this.notify();
        const c = this.client;
        this.closing = (async () => {
            try {
                await c?.close();
                this.remember();
                if (!this.checkCleanup())
                    throw new ContractError('CLEANUP_UNCONFIRMED');
            }
            catch (e) {
                this.lifecycle = 'CLEANUP_UNCONFIRMED';
                this.why = 'CLEANUP_UNCONFIRMED';
                this.notify();
                throw e;
            }
        })();
        return this.closing;
    }
    /** Explicitly poll a late cooperative completion; never repeats close or cancels finalizers. */
    checkCleanup() {
        if (this.lifecycle === 'DETACHED')
            return true;
        if (this.lifecycle === 'ATTACHED' || !this.portClosed || this.portCloseFailed || this.storePending || this.requestsPending || this.actionPending)
            return false;
        this.remember();
        this.client = null;
        this.lifecycle = 'DETACHED';
        if (this.why === 'CLEANUP_UNCONFIRMED')
            this.why = null;
        this.notify();
        return true;
    }
}
