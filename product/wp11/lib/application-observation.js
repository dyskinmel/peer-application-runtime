import { record, string, u64, bool, count, enumValue, list, check, clone, freeze, canonical, validateState } from './validate.js';
function hex(v, n = 64) { string(v, n); check(v.length === n && /^[0-9a-f]+$/.test(v), 'hex'); }
function scopeFields(v) {
    const s = record(v, ['appId', 'spaceId', 'documentId', 'epoch', 'schemaId']);
    string(s.appId, 128);
    hex(s.spaceId);
    hex(s.documentId);
    hex(s.schemaId);
    u64(s.epoch);
    check(s.epoch !== '0', 'epoch');
}
function pinFields(v) {
    scopeFields(v.scope);
    hex(v.storeGeneration, 32);
    hex(v.certificateDigest);
    hex(v.streamId, 32);
    if (v.engineDigest !== null)
        hex(v.engineDigest);
}
export function validateApplicationPin(input) {
    const p = record(input, ['scope', 'storeGeneration', 'certificateDigest', 'streamId', 'engineDigest']);
    pinFields(p);
    return freeze(clone(p));
}
export function validateApplicationObservation(input) {
    const r = record(input, ['profile', 'scope', 'storeGeneration', 'certificateDigest', 'streamId', 'engineDigest', 'sequence', 'revision', 'observedAt', 'authority', 'application', 'operation', 'capabilities', 'restoreReadOnly', 'catalogComplete', 'replicationObserved', 'globalLatestProven', 'productQualified', 'evidenceKind']);
    pinFields(r);
    check(r.profile === 'par-application-observation-local-0036', 'profile');
    u64(r.sequence);
    hex(r.revision);
    string(r.observedAt, 24);
    const date = new Date(r.observedAt);
    check(Number.isFinite(date.getTime()) && date.toISOString() === r.observedAt, 'timestamp');
    bool(r.restoreReadOnly);
    check(r.catalogComplete === false && r.replicationObserved === false && r.globalLatestProven === false && r.productQualified === false && r.evidenceKind === 'trusted-owner-application-observation', 'unsupported claim');
    const s = r.scope;
    const a = record(r.authority, ['state', 'controlHead', 'epoch', 'readerAuthorized']);
    hex(a.controlHead);
    u64(a.epoch);
    check(a.state === 'ACTIVE' && a.readerAuthorized === true && a.epoch === s.epoch, 'read authority');
    const d = record(r.application, ['state', 'revision', 'eventDigest', 'heads', 'inputCount', 'evidenceClass', 'note', 'innerValidated', 'applied', 'recheckedCoreDigest']);
    enumValue(d.state, ['EMPTY', 'CANDIDATE_ONLY', 'CORE_RECHECK_REQUIRED', 'VALIDATED_LOCAL_VIEW']);
    count(d.revision, 64);
    count(d.inputCount, 128);
    list(d.heads, 128, x => hex(x));
    check(d.heads.length === new Set(d.heads).size && canonical(d.heads) === canonical([...d.heads].sort()), 'heads');
    enumValue(d.evidenceClass, ['none', 'candidate', 'core-validated']);
    bool(d.innerValidated);
    bool(d.applied);
    if (d.state === 'EMPTY') {
        check(d.revision === 0 && d.eventDigest === null && d.inputCount === 0 && d.heads.length === 0 && d.evidenceClass === 'none', 'empty');
    }
    else {
        hex(d.eventDigest);
        check(d.revision > 0 && d.inputCount > 0 && d.heads.length > 0 && d.heads.length <= d.inputCount, 'frontier');
        check(d.evidenceClass === (d.state === 'CANDIDATE_ONLY' ? 'candidate' : 'core-validated'), 'evidence');
    }
    if (d.state === 'VALIDATED_LOCAL_VIEW') {
        check(r.engineDigest !== null && d.recheckedCoreDigest === r.engineDigest && d.innerValidated === true && d.applied === true, 'actual-core replay binding');
        const n = record(d.note, ['title', 'body', 'titleConflicts']);
        string(n.title, 1024, 0);
        string(n.body, 262144, 0);
        list(n.titleConflicts, 32, v => { string(v, 1024, 0); check(new TextEncoder().encode(v).length <= 1024, 'conflict bytes'); });
        check(new TextEncoder().encode(n.title).length <= 1024 && new TextEncoder().encode(canonical(n)).length <= 262144, 'note bytes');
    }
    else {
        check(d.note === null && d.innerValidated === false && d.applied === false && d.recheckedCoreDigest === null, 'hidden note');
    }
    const o = record(r.operation, ['id', 'state', 'revision', 'eventDigest']);
    if (o.id !== null)
        hex(o.id, 32);
    enumValue(o.state, ['NOT_QUERIED', 'NOT_OBSERVED', 'OBSERVED_CANDIDATE', 'OBSERVED_APPLICATION_RECORD']);
    if (o.state === 'NOT_QUERIED' || o.state === 'NOT_OBSERVED') {
        check(o.revision === null && o.eventDigest === null && ((o.state === 'NOT_QUERIED') === (o.id === null)), 'no observation');
    }
    else {
        hex(o.id, 32);
        hex(o.eventDigest);
        count(o.revision, 64);
        check(o.revision > 0 && o.revision <= d.revision, 'operation revision');
        check((o.state === 'OBSERVED_CANDIDATE') === (d.evidenceClass === 'candidate'), 'operation evidence');
        if (o.revision === d.revision)
            check(o.eventDigest === d.eventDigest, 'operation digest');
    }
    const c = record(r.capabilities, ['observe', 'inspectApplication', 'sharedCommit', 'sync', 'apply']);
    check(c.observe === true && c.inspectApplication === true && c.sharedCommit === false && c.sync === false && c.apply === false, 'capabilities');
    return freeze(clone(r));
}
function bound(input, pin) {
    const r = validateApplicationObservation(input);
    const actual = { scope: r.scope, storeGeneration: r.storeGeneration, certificateDigest: r.certificateDigest, streamId: r.streamId, engineDigest: r.engineDigest };
    check(canonical(actual) === canonical(pin), 'fixed scope/stream/core', 'APPLICATION_BINDING_MISMATCH');
    return r;
}
export function applicationNotice(input) {
    const r = validateApplicationObservation(input);
    const key = { EMPTY: 'application.not-observed', CANDIDATE_ONLY: 'application.candidate-hidden', CORE_RECHECK_REQUIRED: 'application.recheck-required', VALIDATED_LOCAL_VIEW: 'application.read-only-validated' }[r.application.state];
    return freeze({ key, args: {} });
}
/** Application record persistence is NOT a local-edit commit acknowledgement. */
export function projectApplicationObservation(input, expected) {
    const p = validateApplicationPin(expected), r = bound(input, p), d = r.application, n = d.note;
    const scope = { appId: r.scope.appId, spaceId: r.scope.spaceId, documentId: r.scope.documentId };
    return validateState({ schemaVersion: 1, streamId: r.streamId, sequence: r.sequence, revision: r.revision, snapshotTime: r.observedAt, scope, surface: 'editor',
        capabilities: { host: 'linux', storageClass: 'native-candidate', durableKeeperEligible: false, keyProtection: 'software-encrypted', supportsLocalEffectTransaction: false, background: 'unsupported' },
        supportedCommands: ['open-details'],
        local: { state: 'unknown', storageClass: 'native-candidate', operationId: null, cancellationRequested: false },
        protection: { root: d.eventDigest ?? 'application-not-observed', goal: 0, observations: [], keys: 'unknown', physicalIndependence: 'unknown' },
        connection: { state: 'unknown', peers: 0 }, authority: { state: 'ready', controlHead: r.authority.controlHead, epoch: r.scope.epoch, role: 'reader', sharedWriteAllowed: false },
        document: { read: n ? 'found' : d.state === 'EMPTY' ? 'absent-local' : 'waiting-data', title: n?.title ?? '', text: n?.body ?? '', frontier: 'application-event:' + (d.eventDigest ?? 'none'), innerValidated: d.innerValidated, applied: d.applied, conflicts: n?.titleConflicts.map(value => ({ value, provenance: 'owner-pinned-application-replay' })) ?? [], privateDraft: false, knownCatalogComplete: false, missingObjects: '0' },
        recovery: { phase: 'idle', received: '0', total: null, recipientValidated: false, keys: 'unknown', missingObjects: '0' }, rpc: { state: 'idle', operationId: null },
        invite: { phase: 'none', role: 'reader', targetDevice: null, manualAvailable: false, fileAvailable: false }, contribution: { state: 'disabled', storageBudget: '0', relayBudget: '0', activeLeases: 0 }, presence: 'unknown', diagnostic: null, previews: [],
        evidence: { kind: 'runtime-observation', references: [applicationNotice(r).key, 'application-operation:' + r.operation.state, 'store-generation:' + r.storeGeneration, 'restore-read-only:' + String(r.restoreReadOnly), 'replication-and-network:not-observed', 'application-is-not-local-edit-commit'] } });
}
/** Explicit reads only. Erase exposed note state before I/O and on every failure.
 * This does not erase strings securely, nor erase separately-owned private drafts.
 */
export class ApplicationReadBinding {
    port;
    pin;
    last;
    view;
    busy = false;
    closed = false;
    phase = 'CURRENT';
    knownOperations = new Map();
    constructor(expected, initial, port) {
        this.port = port;
        this.pin = validateApplicationPin(expected);
        this.last = bound(initial, this.pin);
        this.view = projectApplicationObservation(this.last, this.pin);
        this.rememberOperation(this.last);
    }
    get current() { return this.view; }
    get status() { return this.phase; }
    get observation() { return this.phase === 'CURRENT' ? this.last : null; }
    rememberOperation(r) {
        const o = r.operation;
        if (o.id === null)
            return;
        const known = this.knownOperations.get(o.id);
        if (known !== undefined)
            check(known === canonical(o), 'recorded outcome changed', 'APPLICATION_RESULT_CHANGED');
        if (o.state === 'OBSERVED_CANDIDATE' || o.state === 'OBSERVED_APPLICATION_RECORD') {
            check(known !== undefined || this.knownOperations.size < 64, 'known results bound', 'RESOURCE_LIMIT');
            this.knownOperations.set(o.id, canonical(o));
        }
    }
    mask(status) {
        this.phase = status;
        this.view = validateState({ ...this.view, revision: this.last.revision + ':' + status,
            authority: { ...this.view.authority, state: 'pending', sharedWriteAllowed: false },
            document: { ...this.view.document, read: 'waiting-data', title: '', text: '', innerValidated: false, applied: false, conflicts: [] },
            evidence: { kind: 'runtime-observation', references: ['application.observation.' + status.toLowerCase(), 'private-draft-not-modified'] } });
    }
    close() { this.closed = true; this.mask('CLOSED'); }
    async refresh(operationId = null) {
        check(!this.closed, 'closed', 'APPLICATION_BINDING_CLOSED');
        check(!this.busy, 'busy', 'APPLICATION_BINDING_BUSY');
        if (operationId !== null)
            hex(operationId, 32);
        this.busy = true;
        this.mask('CHECKING');
        try {
            const raw = await this.port.observe(operationId);
            check(!this.closed, 'closed', 'APPLICATION_BINDING_CLOSED');
            const next = bound(raw, this.pin);
            check(next.operation.id === operationId, 'operation id', 'OPERATION_MISMATCH');
            check(BigInt(next.sequence) >= BigInt(this.last.sequence), 'old response', 'STALE_VIEW');
            if (next.sequence === this.last.sequence || next.revision === this.last.revision)
                check(canonical(next) === canonical(this.last), 'token reuse', 'REVISION_REUSED');
            const prev = this.last.application, d = next.application;
            check(d.revision >= prev.revision, 'application revision', 'APPLICATION_FRONTIER_REGRESSED');
            if (d.revision === prev.revision) {
                check(d.eventDigest === prev.eventDigest && d.evidenceClass === prev.evidenceClass && d.inputCount === prev.inputCount && canonical(d.heads) === canonical(prev.heads), 'same frontier', 'APPLICATION_FRONTIER_CHANGED');
                if (d.note !== null && prev.note !== null)
                    check(canonical(d.note) === canonical(prev.note), 'same materialization', 'APPLICATION_FRONTIER_CHANGED');
            }
            this.rememberOperation(next);
            this.last = next;
            this.view = projectApplicationObservation(next, this.pin);
            this.phase = 'CURRENT';
            return this.view;
        }
        catch (error) {
            if (!this.closed)
                this.mask('UNAVAILABLE');
            throw error;
        }
        finally {
            this.busy = false;
        }
    }
}
