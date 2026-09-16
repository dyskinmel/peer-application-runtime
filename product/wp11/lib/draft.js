import { validateDraft, validateDraftEvent, validateState, string, count, check, clone, freeze, canonical } from './validate.js';
import { sharedWriteEligible, present } from './presenter.js';
import { message } from './messages.js';
export function toScalarOffset(text, utf16) {
    string(text, 1048576, 0);
    count(utf16, text.length);
    if (utf16 > 0 && utf16 < text.length) {
        const c = text.charCodeAt(utf16);
        check(c < 0xdc00 || c > 0xdfff, 'offset splits scalar');
    }
    return [...text.slice(0, utf16)].length;
}
export function toUtf16Offset(text, scalar) { string(text, 1048576, 0); const cs = [...text]; count(scalar, cs.length); return cs.slice(0, scalar).join('').length; }
export function createDraft(text, frontier) { string(text, 1048576, 0); string(frontier); return freeze({ schemaVersion: 1, text, baseText: text, baseFrontier: frontier, selection: { anchor: 0, focus: 0 }, composing: false, dirty: false, requiresRebase: false, persisted: false, pendingRemote: null, lastRemote: null }); }
export function reduceDraft(previous, event) {
    const d = validateDraft(previous), e = validateDraftEvent(event);
    toScalarOffset(d.text, d.selection.anchor);
    toScalarOffset(d.text, d.selection.focus);
    switch (e.type) {
        case 'composition-start': return freeze({ ...d, composing: true });
        case 'composition-end': return freeze({ ...d, composing: false });
        case 'authority-changed': return freeze({ ...d, requiresRebase: true });
        case 'input':
            toScalarOffset(e.text, e.anchor);
            toScalarOffset(e.text, e.focus);
            return freeze({ ...d, text: e.text, selection: { anchor: e.anchor, focus: e.focus }, dirty: e.text !== d.baseText });
        case 'remote': {
            const r = { text: e.text, frontier: e.frontier, sequence: e.sequence };
            if (d.lastRemote) {
                const a = BigInt(d.lastRemote.sequence), b = BigInt(e.sequence);
                check(b >= a, 'older remote', 'STALE_VIEW');
                if (a === b) {
                    check(canonical(d.lastRemote) === canonical(r), 'remote sequence reused', 'REVISION_REUSED');
                    return freeze(d);
                }
            }
            return freeze({ ...d, pendingRemote: r, lastRemote: r });
        }
        case 'accept-remote': {
            check(!d.dirty && !d.composing && !d.requiresRebase, 'keep private draft until explicit review', 'DRAFT_REVIEW_REQUIRED');
            check(d.pendingRemote, 'no pending remote');
            const r = d.pendingRemote;
            return freeze({ ...d, text: r.text, baseText: r.text, baseFrontier: r.frontier, pendingRemote: null, selection: { anchor: 0, focus: 0 } });
        }
    }
}
/** Minimal scalar splice, not a CRDT merge/rebase. No write or success receipt occurs here. */
export function prepareDraftCommit(input, previous, operationId) {
    const s = validateState(input), d = validateDraft(previous);
    string(operationId);
    check(sharedWriteEligible(s), 'shared editing unavailable', 'ACTION_DISABLED');
    check(!d.composing && !d.requiresRebase && d.pendingRemote === null && d.baseFrontier === s.document.frontier && d.baseText === s.document.text, 'review changed base/draft', 'DRAFT_REVIEW_REQUIRED');
    check(!s.document.conflicts.length, 'review conflicts', 'DRAFT_REVIEW_REQUIRED');
    check(d.dirty, 'no draft change', 'DRAFT_UNCHANGED');
    const a = [...d.baseText], b = [...d.text];
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start])
        start++;
    let suffix = 0;
    while (suffix < a.length - start && suffix < b.length - start && a[a.length - 1 - suffix] === b[b.length - 1 - suffix])
        suffix++;
    return freeze({ kind: 'document.text-splice-candidate', operationId, expectedRevision: s.revision, streamId: s.streamId, sequence: s.sequence, scope: clone(s.scope), effectExecuted: false, requiresDomainRevalidation: true, payload: { path: ['body'], position: { scalarOffset: start, frontier: d.baseFrontier }, deleteScalars: a.length - start - suffix, insert: b.slice(start, b.length - suffix).join('') } });
}
/** Compose snapshot status with a separate volatile edit buffer. Never label dirty text saved. */
export function presentEditor(input, previous) {
    const s = validateState(input), d = validateDraft(previous), vm = present(s);
    const needsReview = d.requiresRebase || d.pendingRemote !== null || d.baseFrontier !== s.document.frontier;
    const primary = d.composing ? message('draft.composing') : needsReview ? message('draft.review') : d.dirty ? message('draft.unsaved') : vm.primary;
    return freeze({ ...vm, primary, draft: { ...d, message: primary }, draftCommitEligible: vm.sharedWriteEligible && d.dirty && !d.composing && !needsReview && !s.document.conflicts.length && d.baseText === s.document.text });
}
