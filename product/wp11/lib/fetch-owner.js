/** Explicit owner commands. Transport is injected, never discovered or retried.
 * The binding validates the existing Python observation; candidates are never
 * copied into shared/private note text. Apply is deliberately not exported.
 */
import { check, record, count, list, enumValue, clone, freeze, ContractError } from './validate.js';
import { FetchReadBinding, validateFetchPin, presentFetchObservation } from './fetch-observation.js';
export const FETCH_OWNER_PROTOCOL = 'par-owner-fetch-0049';
export const FETCH_OWNER_OPERATIONS = ['accept', 'close', 'fetch', 'inquire', 'observe', 'propose', 'resume', 'validate'];
const hex = (v, n = 64) => check(typeof v === 'string' && v.length === n && /^[0-9a-f]+$/.test(v), 'identifier');
const code = (e) => {
    const v = e && typeof e === 'object' ? Object.getOwnPropertyDescriptor(e, 'code')?.value : undefined;
    return typeof v === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(v) ? v : 'OWNER_REQUEST_FAILED';
};
export const validateFetchOwnerContext = (v) => validateFetchPin(v);
function meta(value) {
    const v = record(value, ['profile', 'observation', 'proposal', 'selection', 'progress', 'resumeRequired', 'operations']);
    check(v.profile === FETCH_OWNER_PROTOCOL, 'owner profile');
    check(typeof v.resumeRequired === 'boolean', 'resume flag');
    list(v.operations, FETCH_OWNER_OPERATIONS.length, x => enumValue(x, FETCH_OWNER_OPERATIONS));
    check(new Set(v.operations).size === v.operations.length && v.operations.includes('observe'), 'operations');
    if (v.proposal !== null) {
        const p = record(v.proposal, ['id', 'planDigest', 'records', 'bytes', 'queries']);
        hex(p.id);
        count(p.records, 64);
        count(p.bytes, 8388608);
        count(p.queries, 32);
        if (p.planDigest === null)
            check(p.records === 0 && p.bytes === 0, 'empty proposal');
        else {
            hex(p.planDigest);
            check(p.records > 0 && p.bytes > 0, 'nonempty proposal');
        }
    }
    if (v.selection !== null) {
        const p = record(v.selection, ['planDigest', 'records', 'bytes']);
        hex(p.planDigest);
        count(p.records, 64);
        count(p.bytes, 8388608);
        check(p.records > 0 && p.bytes > 0, 'nonempty selection');
    }
    check((v.selection === null) === (v.progress === null), 'selection progress pair');
    if (v.progress !== null) {
        const p = record(v.progress, ['profile', 'planDigest', 'state', 'reason', 'stored', 'total', 'items', 'applied', 'localCommitted', 'replicated', 'acknowledged', 'observationOnly']);
        check(p.profile === 'par-secure-fetch-local-0045', 'fetch profile');
        hex(p.planDigest);
        count(p.stored, 64);
        count(p.total, 64);
        check(p.stored <= p.total, 'stored total');
        if (p.state === 'COMPLETE_PENDING')
            check(p.stored === p.total, 'incomplete marked complete');
        enumValue(p.state, ['NOT_RECONCILED', 'REVIEW_REQUIRED', 'COMPLETE_PENDING', 'PARTIAL_PENDING', 'STOPPED', 'RECONCILE_REQUIRED', 'FETCHING']);
        check(p.reason === null || (typeof p.reason === 'string' && /^[A-Z_]{1,80}$/.test(p.reason)), 'reason');
        for (const k of ['applied', 'localCommitted', 'replicated', 'acknowledged'])
            check(p[k] === false, 'non-claim');
        check(p.observationOnly === true, 'observation only');
        list(p.items, 64, i => {
            const r = record(i, ['envelopeId', 'state', 'candidateState']);
            hex(r.envelopeId);
            enumValue(r.state, ['NOT_OBSERVED', 'INBOX_STORED', 'OUTCOME_UNKNOWN', 'REQUESTING', 'FETCH_FAILED']);
            enumValue(r.candidateState, [null, 'NOT_OBSERVED', 'WAITING_DEPENDENCIES', 'READY_FOR_CORE', 'QUARANTINED', 'WAITING_AUTHORITY', 'REBASE_REQUIRED', 'INVALID_DEPENDENCY_GRAPH', 'RESOURCE_BLOCKED']);
        });
        const rows = p.items;
        check(rows.length === p.total && new Set(rows.map(r => r.envelopeId)).size === rows.length, 'item count');
        check(rows.filter(r => r.state === 'INBOX_STORED').length === p.stored, 'stored count');
        check(v.selection !== null && v.selection.planDigest === p.planDigest && v.selection.records === p.total, 'progress selection');
    }
    return v;
}
function options(value) {
    check(value !== null && typeof value === 'object', 'options');
    const keys = Object.keys(value);
    check(keys.every(k => k === 'signal' || k === 'timeoutMs'), 'options');
    const v = record(value, keys);
    check(v.signal === undefined || v.signal instanceof AbortSignal, 'signal');
    const ms = v.timeoutMs ?? 5000;
    count(ms, 60000);
    check(ms >= 50, 'timeout');
    return { signal: v.signal, timeoutMs: ms };
}
export class FetchOwnerClient {
    port;
    pin;
    binding;
    staged;
    operation = null;
    busy = false;
    closed = false;
    epoch = 0;
    aborter = null;
    original = null;
    mustResume = false;
    state = freeze({ status: 'NOT_OBSERVED', snapshot: null, reason: null, originalPlanDigest: null, resumeRequired: false });
    constructor(pin, port) {
        this.port = port;
        this.pin = validateFetchPin(pin);
        check(port && typeof port.request === 'function' && typeof port.close === 'function', 'owner port');
        this.binding = new FetchReadBinding(this.pin, { observe: async () => this.staged });
    }
    get current() { return this.state; }
    set(status, snapshot = null, reason = null) {
        this.state = freeze({ status, snapshot, reason, originalPlanDigest: this.original, resumeRequired: this.mustResume });
    }
    currentSnapshot(op) {
        check(!this.closed, 'closed', 'OWNER_CLIENT_CLOSED');
        check(!this.busy, 'busy', 'OWNER_CLIENT_BUSY');
        check(this.state.status === 'CURRENT' && this.state.snapshot !== null, 'observe first', 'OWNER_OBSERVE_REQUIRED');
        check(this.state.snapshot.operations.includes(op), 'grant', 'OWNER_OPERATION_DENIED');
        return this.state.snapshot;
    }
    async invoke(op, args, opts = {}, intent) {
        check(!this.closed, 'closed', 'OWNER_CLIENT_CLOSED');
        check(!this.busy, 'busy', 'OWNER_CLIENT_BUSY');
        const o = options(opts);
        check(!o.signal?.aborted, 'cancelled', 'CANCELLED');
        if (intent !== undefined)
            this.original = intent;
        this.busy = true;
        this.operation = op;
        const epoch = ++this.epoch;
        const aborter = new AbortController();
        this.aborter = aborter;
        let timer;
        let why = 'CANCELLED';
        const forward = () => aborter.abort();
        o.signal?.addEventListener('abort', forward, { once: true });
        const active = () => { check(!this.closed && this.epoch === epoch, 'late response', 'OWNER_STALE_RESPONSE'); check(!aborter.signal.aborted, 'cancelled', why); };
        let abortListener = () => { };
        this.set('BUSY');
        try {
            const cancelled = new Promise((_, reject) => { abortListener = () => reject(new ContractError(why)); aborter.signal.addEventListener('abort', abortListener, { once: true }); });
            timer = setTimeout(() => { why = 'OWNER_CLIENT_TIMEOUT'; aborter.abort(); }, o.timeoutMs);
            active();
            const reply = this.port.request(op, { context: clone(this.pin), ...args, timeoutMs: o.timeoutMs }, aborter.signal);
            const raw = await Promise.race([reply, cancelled]);
            active();
            const envelope = meta(raw);
            this.staged = envelope.observation;
            const checked = await this.binding.refresh();
            active();
            check(checked.observation !== null, 'missing observation');
            const value = freeze(clone({ ...envelope, observation: checked.observation }));
            if (op === 'accept' || op === 'resume' || op === 'fetch')
                check(value.selection?.planDigest === this.original || this.original === null && value.selection === null, 'selected plan mismatch', 'OWNER_PLAN_MISMATCH');
            if (op === 'accept' || op === 'resume')
                this.mustResume = value.resumeRequired;
            else
                this.mustResume = this.mustResume || value.resumeRequired;
            this.set('CURRENT', value);
            return value;
        }
        catch (e) {
            if (op === 'accept' || op === 'fetch' || op === 'resume')
                this.mustResume = true;
            if (!this.closed && this.epoch === epoch)
                this.set('UNAVAILABLE', null, code(e));
            throw e;
        }
        finally {
            if (timer !== undefined)
                clearTimeout(timer);
            o.signal?.removeEventListener('abort', forward);
            aborter.signal.removeEventListener('abort', abortListener);
            if (this.epoch === epoch) {
                this.busy = false;
                this.aborter = null;
                this.operation = null;
            }
        }
    }
    async observe(opts = {}) { return this.invoke('observe', {}, opts); }
    async propose(opts = {}) { const s = this.currentSnapshot('propose'); return this.invoke('propose', { expectedRevision: s.observation.revision }, opts); }
    async accept(opts = {}) { const s = this.currentSnapshot('accept'); check(s.proposal !== null, 'no proposal'); return this.invoke('accept', { expectedRevision: s.observation.revision, proposalId: s.proposal.id }, opts, s.proposal.planDigest); }
    async fetch(opts = {}) { const s = this.currentSnapshot('fetch'); check(!this.mustResume && !s.resumeRequired, 'resume required', 'OWNER_RESUME_REQUIRED'); check(s.selection !== null, 'no selection'); return this.invoke('fetch', { expectedRevision: s.observation.revision, planDigest: s.selection.planDigest }, opts, s.selection.planDigest); }
    async resume(planDigest, opts = {}) { hex(planDigest); const s = this.currentSnapshot('resume'); return this.invoke('resume', { expectedRevision: s.observation.revision, planDigest }, opts, planDigest); }
    async validate(opts = {}) { const s = this.currentSnapshot('validate'); return this.invoke('validate', { expectedRevision: s.observation.revision }, opts); }
    async inquire(operationId, expectedApplyRevision, opts = {}) { hex(operationId, 32); count(expectedApplyRevision, 63); const s = this.currentSnapshot('inquire'); return this.invoke('inquire', { expectedRevision: s.observation.revision, operationId, expectedApplyRevision }, opts); }
    cancel() { this.aborter?.abort(); }
    async close() {
        if (this.closed)
            return;
        if (this.operation === 'accept' || this.operation === 'resume' || this.operation === 'fetch')
            this.mustResume = true;
        this.operation = null;
        this.closed = true;
        ++this.epoch;
        this.aborter?.abort();
        this.binding.close();
        this.set('CLOSED');
        let timer;
        try {
            await Promise.race([this.port.close(), new Promise((_, reject) => { timer = setTimeout(() => reject(new ContractError('OWNER_CLOSE_TIMEOUT')), 1000); })]);
        }
        finally {
            if (timer !== undefined)
                clearTimeout(timer);
        }
    }
}
/** Borrowed owner. This view never closes a borrowed port on destroy. */
export function mountFetchControls(root, client, initialLocale = 'ja') {
    let alive = true, locale = initialLocale, localError = '';
    enumValue(locale, ['ja', 'en']);
    const d = root.ownerDocument, panel = d.createElement('section'), heading = d.createElement('h2'), status = d.createElement('p'), detail = d.createElement('p'), buttons = d.createElement('div');
    panel.setAttribute('data-fetch-owner', 'true');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const digest = d.createElement('input'), operation = d.createElement('input'), revision = d.createElement('input');
    digest.maxLength = 64;
    operation.maxLength = 32;
    revision.type = 'number';
    revision.min = '0';
    revision.max = '63';
    revision.value = '0';
    const labels = { observe: ['候補を確認', 'Observe'], propose: ['不足の取得を提案', 'Propose'], accept: ['この計画を採用', 'Accept plan'], fetch: ['候補を取得', 'Fetch'], validate: ['明示的に検証', 'Validate'], resume: ['計画SHAで再照合', 'Resume by SHA'], inquire: ['元の操作IDを照会', 'Inquire'], cancel: ['取消しを要求', 'Cancel'], close: ['接続を閉じる', 'Close'] };
    const controls = new Map();
    const run = async (fn) => { localError = ''; try {
        const p = fn();
        render();
        await p;
    }
    catch (e) {
        localError = code(e);
    }
    finally {
        render();
    } };
    const actions = { observe: () => client.observe(), propose: () => client.propose(), accept: () => client.accept(), fetch: () => client.fetch(), validate: () => client.validate(), resume: () => client.resume(digest.value), inquire: () => client.inquire(operation.value, Number(revision.value)), cancel: async () => client.cancel(), close: () => client.close() };
    for (const action of Object.keys(labels)) {
        const b = d.createElement('button');
        b.type = 'button';
        b.dataset['fetchAction'] = action;
        b.onclick = () => { void run(actions[action]); };
        controls.set(action, b);
        buttons.append(b);
    }
    panel.append(heading, status, detail, digest, operation, revision, buttons);
    root.replaceChildren(panel);
    function render() {
        if (!alive)
            return;
        const s = client.current, v = s.snapshot;
        heading.textContent = locale === 'ja' ? '取得候補（文書への適用とは別）' : 'Fetch candidates (separate from document application)';
        digest.setAttribute('aria-label', locale === 'ja' ? '外部保持した計画SHA-256' : 'Externally retained plan SHA-256');
        operation.setAttribute('aria-label', locale === 'ja' ? '元の適用操作ID' : 'Original application operation ID');
        revision.setAttribute('aria-label', locale === 'ja' ? '期待する適用revision' : 'Expected application revision');
        status.textContent = localError || s.reason || (s.status === 'BUSY' ? (locale === 'ja' ? '処理中。取消しは保存の巻戻しではありません。' : 'Working. Cancel is not rollback.') : v ? presentFetchObservation(v.observation, locale).message : (locale === 'ja' ? '候補状態は未確認です。明示的に確認してください。' : 'Candidate state is unconfirmed. Explicitly observe it.'));
        detail.textContent = v?.proposal ? `${v.proposal.records} / ${v.proposal.bytes} bytes / SHA: ${v.proposal.planDigest ?? '-'}` : s.originalPlanDigest ? `SHA: ${s.originalPlanDigest}` : '';
        for (const [a, b] of controls) {
            b.textContent = labels[a][locale === 'ja' ? 0 : 1];
            b.disabled = s.status === 'CLOSED' || (a === 'cancel' ? s.status !== 'BUSY' : a === 'close' ? false : s.status === 'BUSY' || a !== 'observe' && (!v || !v.operations.includes(a)));
            if (a === 'accept')
                b.disabled ||= !v?.proposal;
            if (a === 'fetch')
                b.disabled ||= !v?.selection || s.resumeRequired || !!v?.resumeRequired;
        }
    }
    render();
    return { async refresh() { await run(() => client.observe()); }, setLocale(next) { enumValue(next, ['ja', 'en']); locale = next; render(); }, destroy() { alive = false; root.replaceChildren(); } };
}
