import { validateState, freeze, scopeKey, canonical } from './validate.js';
import { message as m } from './messages.js';
export function matchingPreview(s, kind) {
    const p = s.previews.find(p => p.kind === kind);
    const target = kind === 'approve-invite' ? s.invite.targetDevice : kind === 'activate-recovery' ? s.protection.root : kind === 'force-stop' ? s.scope.spaceId : p?.target;
    return p && p.revision === s.revision && p.scopeKey === scopeKey(s.scope) && p.target === target ? p : undefined;
}
export function sharedWriteEligible(s) { return s.authority.sharedWriteAllowed && s.authority.state === 'ready' && ['editor', 'owner'].includes(s.authority.role) && s.document.read === 'found' && s.document.innerValidated && s.document.applied && s.recovery.phase === 'idle' && s.protection.keys === 'available' && s.local.state === 'committed' && s.diagnostic === null; }
function action(s, kind) {
    const confirmation = kind === 'force-stop' ? 'explicit-risk' : ['approve-invite', 'activate-recovery'].includes(kind) ? 'preview' : 'none';
    let disabled = null;
    if (!s.supportedCommands.includes(kind))
        disabled = 'reason.unsupported';
    else if (kind === 'approve-invite' && (s.authority.role !== 'owner' || s.authority.state !== 'ready' || s.invite.phase !== 'review'))
        disabled = 'reason.not-authorized';
    else if (kind === 'activate-recovery' && (!s.recovery.recipientValidated || s.recovery.phase !== 'review' || s.recovery.keys !== 'available' || s.recovery.missingObjects !== '0' || s.authority.state === 'fork'))
        disabled = 'reason.unverified';
    else if (['export', 'export-partial'].includes(kind) && (s.protection.keys !== 'available' || (s.document.read !== 'found' && !s.document.privateDraft)))
        disabled = 'reason.unavailable';
    else if (confirmation !== 'none' && !matchingPreview(s, kind))
        disabled = 'reason.preview';
    return { kind, enabled: disabled === null, disabledReason: disabled, confirmation, targetRevision: s.revision, target: matchingPreview(s, kind)?.target ?? null };
}
export function present(input) {
    const s = validateState(input);
    const local = m(s.local.state === 'committed' && s.local.storageClass === 'browser-best-effort' ? 'local.browser' : 'local.' + s.local.state);
    const obs = s.protection.observations.filter(o => o.manifest === s.protection.root && o.byteComplete);
    const eligible = obs.filter(o => o.semanticClosure === 'verified' && o.freshness === 'fresh' && o.storageClass !== 'browser-best-effort' && s.protection.keys === 'available');
    let protection = obs.length === 0 ? m('copies.none') : m('copies.observed', { count: obs.length });
    if (obs.length) {
        if (obs.some(o => o.freshness === 'stale'))
            protection = m('copies.stale');
        else if (obs.some(o => o.freshness === 'unknown'))
            protection = m('copies.unknown');
        else if (obs.some(o => o.semanticClosure !== 'verified'))
            protection = m('copies.byte-only');
        else if (s.protection.keys !== 'available')
            protection = m('copies.keys-missing');
    }
    if (s.evidence.kind === 'runtime-observation' && s.protection.goal === 0 && obs.length === 0)
        protection = m('copies.not-observed');
    const authority = m('authority.' + s.authority.state);
    const document = s.document.conflicts.length > 1 ? m(s.local.state === 'committed' ? 'document.conflict' : 'document.conflict-pending') : m(s.document.read === 'found' && !s.document.applied ? 'document.unapplied' : 'document.' + s.document.read);
    const connection = m('connection.' + s.connection.state);
    const r = s.recovery;
    let recovery = m('recovery.' + r.phase);
    if (['review', 'read-only'].includes(r.phase) && !r.recipientValidated)
        recovery = m('recovery.unverified');
    if (r.phase === 'verifying' && (r.total === null || r.received !== r.total))
        recovery = m('recovery.unverified');
    const rpc = m('rpc.' + s.rpc.state);
    const presence = m('presence.' + s.presence);
    let primary = local;
    let kinds = ['open-details'];
    switch (s.surface) {
        case 'workspace':
            if (s.authority.state === 'fork') {
                primary = authority;
                kinds = ['inspect-fork', 'export'];
            }
            else if (s.document.read === 'absent-local') {
                primary = m('workspace.empty');
                kinds = ['create-space', 'import-data'];
            }
            else {
                primary = document;
                kinds = ['open-details', 'export'];
            }
            break;
        case 'protection':
            if (s.local.state !== 'committed') {
                primary = local;
                kinds = ['open-details'];
            }
            else if (obs.length === 0) {
                primary = local;
                kinds = ['add-copy', 'open-details'];
            }
            else if (obs.some(o => o.freshness !== 'fresh')) {
                primary = protection;
                kinds = ['retry-connect', 'open-details'];
            }
            else if (obs.some(o => o.semanticClosure !== 'verified') || s.protection.keys !== 'available') {
                primary = protection;
                kinds = ['verify-recovery', 'open-details'];
            }
            else {
                primary = protection;
                kinds = ['open-details', 'export'];
            }
            break;
        case 'invite':
            if (s.invite.phase === 'pending') {
                primary = m('invite.pending');
                kinds = ['copy-request', 'dismiss'];
            }
            else if (s.invite.phase === 'review') {
                primary = m('invite.' + (s.invite.role === 'opaque-keeper' ? 'keeper' : s.invite.role));
                kinds = ['approve-invite', 'dismiss'];
            }
            else if (s.invite.phase === 'stale') {
                primary = m('invite.stale');
                kinds = ['review-invite', 'dismiss'];
            }
            else {
                primary = m('invite.none');
                kinds = ['review-invite', 'dismiss'];
            }
            break;
        case 'editor':
            if (s.authority.state === 'rebase-required' || s.document.privateDraft) {
                primary = m('authority.rebase-required');
                kinds = ['review-rebase', 'export'];
            }
            else if (s.authority.state === 'fork') {
                primary = authority;
                kinds = ['inspect-fork', 'export'];
            }
            else {
                primary = document;
                kinds = s.document.conflicts.length > 1 ? ['review-conflict', 'export'] : ['open-details', 'export'];
            }
            break;
        case 'recovery':
            primary = recovery;
            kinds = r.phase === 'fetching' ? ['pause-recovery'] : r.phase === 'obtaining-keys' ? ['provide-key', 'export-diagnostics'] : r.phase === 'partial' ? ['export-partial', 'retry-connect'] : r.phase === 'review' ? ['activate-recovery', 'dismiss'] : ['open-details'];
            break;
        case 'contribution':
            primary = m('contribution.' + s.contribution.state);
            kinds = s.contribution.state === 'review-stop' ? ['force-stop', 'dismiss'] : ['review-contribution'];
            break;
        case 'diagnostics':
            primary = m(s.diagnostic === 'storage-full' ? 'diagnostics.storage-full' : 'diagnostics.normal');
            kinds = s.diagnostic === 'storage-full' ? ['choose-folder', 'export-diagnostics'] : ['open-details', 'export-diagnostics'];
            break;
        case 'connectivity':
            primary = connection;
            kinds = s.connection.state === 'relay-required' ? ['review-relay', 'retry-connect'] : ['retry-connect', 'open-details'];
            break;
        case 'rpc':
            primary = rpc;
            kinds = s.rpc.state === 'unknown' || s.rpc.state === 'pending' ? ['inspect-operation'] : ['open-details'];
            break;
        case 'browser':
            primary = local;
            kinds = ['add-copy', 'export'];
            break;
        case 'presence':
            primary = presence;
            kinds = ['open-details'];
            break;
    }
    if (['editor', 'protection'].includes(s.surface) && s.local.state === 'unknown' && s.local.operationId !== null && !kinds.includes('inspect-operation'))
        kinds = ['inspect-operation', ...kinds];
    const { supportedCommands: _commands, previews: _previews, ...rest } = s;
    const pendingOperations = [...new Set([...(s.local.state === 'pending' || s.local.state === 'unknown' ? [s.local.operationId] : []), ...(s.rpc.state === 'pending' || s.rpc.state === 'unknown' ? [s.rpc.operationId] : [])].filter((v) => v !== null))];
    const percent = r.total === null || r.total === '0' ? null : Number(BigInt(r.received) * 100n / BigInt(r.total));
    return freeze({ ...rest, primary, actions: kinds.map(k => action(s, k)), pendingOperations, sharedWriteEligible: sharedWriteEligible(s), productQualified: false,
        local: { ...s.local, message: local }, protection: { ...s.protection, message: protection, observedCopies: obs.length, verifiedRecoverableCopies: eligible.length, goalObserved: eligible.length >= s.protection.goal && s.protection.goal > 0 },
        connection: { ...s.connection, message: connection }, document: { ...s.document, message: document }, presence: { state: s.presence, message: presence },
        recovery: { ...s.recovery, message: recovery, writable: false, progress: { kind: 'bytes', received: r.received, total: r.total, percent, overallPercent: null } },
        details: { authority, rpc, scope: s.scope, evidence: s.evidence } });
}
/** Return only changed status messages, never body edits, focus moves or timers. */
export function announcements(previous, current) {
    const left = [previous.local.message, previous.protection.message, previous.details.authority, previous.recovery.message, previous.details.rpc];
    const right = [current.local.message, current.protection.message, current.details.authority, current.recovery.message, current.details.rpc];
    return freeze(right.filter((v, i) => canonical(v) !== canonical(left[i])));
}
