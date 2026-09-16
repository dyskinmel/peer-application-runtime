import { mountFetchControls } from './fetch-owner.js';
import { mountApplicationControls } from './application-controls.js';
import { checkDraftLoad, checkDraftReceipt } from './draft-session.js';
import { restoreDraft } from './draft-vault.js';
import { validateState, canonical, clone, ContractError, scopeKey, scope as checkScope } from './validate.js';
import { formatMessage } from './messages.js';
import { advanceSnapshot, prepareCommand } from './commands.js';
import { createDraft, reduceDraft, presentEditor } from './draft.js';
let instance = 0;
const newId = () => Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
const words = {
    title: ['共有ノート', 'Shared notes'], details: ['状態の詳細', 'State details'], body: ['ノート本文', 'Note body'],
    snapshotRuntime: ['共有データのローカル保存結果', 'Local storage outcome for shared data'],
    snapshot: ['保存済みの共有スナップショット', 'Stored shared snapshot'], copies: ['ほかの端末での保管', 'Other-device retention'], connection: ['現在の接続', 'Current connection'],
    actions: ['利用可能な操作', 'Available actions'], unavailable: ['実行先が未接続です。共有への保存・同期は実行しません。', 'Runtime adapter is not connected. No shared save or sync is performed.'],
    privateTitle: ['この端末の暗号化下書き', 'Encrypted draft on this device'], save: ['下書きを保存', 'Save private draft'], restore: ['保存済み下書きを読み込む', 'Restore saved draft'],
    inspect: ['保存結果を照合', 'Inspect save outcome'], volatile: ['下書きはメモリー内のみです。終了・再読み込みで失われます。', 'Draft is memory-only. Closing or reloading loses it.'],
    unsaved: ['この下書きはまだ端末に保存されていません。', 'This draft has not yet been saved on this device.'], saving: ['暗号化した下書きを保存しています…', 'Saving the encrypted private draft…'],
    saved: ['この下書きを端末に保存しました。共有・複製はしていません。', 'Private draft saved on this device. Not shared or replicated.'],
    storedOther: ['保存済みの下書きがあります。内容を確認して読み込んでください。', 'A saved draft is available. Review before restoring.'],
    conflict: ['別の編集が先に保存されました。編集中の下書きは保持しています。上書きせず、保存済み下書きを確認してください。', 'Another edit was saved first. Your draft is retained. Inspect the stored draft before replacing it.'],
    unknown: ['保存結果を確認できません。自動再試行せず、結果を照合してください。', 'Save outcome is unknown. Inspect it; no automatic retry occurs.'],
    notConfirmed: ['保存は確認されませんでした。下書きは保持しています。', 'Save not confirmed. The edit buffer is retained.'],
    localOnly: ['端末内の私有コピーです。ブラウザーによる削除や鍵紛失には別の備えが必要です。', 'A private local copy only. Storage eviction and key loss require a separate recovery plan.'],
    review: ['確認が必要です', 'Review required'], confirm: ['確認して続ける', 'Confirm and continue'], cancel: ['キャンセル', 'Cancel'],
    check: ['対象と影響を確認しました', 'I reviewed the target and impact'], replace: ['編集中の下書きを、保存された下書きに置き換えます。共有データは変更しません。', 'Replace the current edit buffer with the stored draft. Shared data is unchanged.'],
    accepted: ['実行先へ渡しました。完了はまだ確認していません。', 'Handed to the runtime. Completion is not yet confirmed.'],
    stale: ['状態が変わりました。内容を確認し直してください。', 'State changed. Review the current details again.'],
    observed: ['Storeの保存結果を照合しました。共有への書き込みは実行していません。', 'Store outcome inspected. No shared write was executed.'],
    runtime: ['検証したStore観測を表示しています。本文のCRDT適用・共有編集は未接続です。', 'Verified Store observation. CRDT materialization and shared editing are not connected.'],
    synthetic: ['合成データのUI検証用です。実際の共同編集・同期には接続していません。', 'Synthetic UI reference. Not connected to collaborative editing or sync.']
};
function fingerprint(d) { return canonical({ text: d.text, baseText: d.baseText, baseFrontier: d.baseFrontier, pendingRemote: d.pendingRemote, requiresRebase: d.requiresRebase }); }
export function mountReference(root, input, options = {}) {
    let state = validateState(input), draft = createDraft(state.document.text, state.document.frontier), locale = options.locale ?? 'ja';
    if (options.fetchOwner && scopeKey(options.fetchOwner.pin.scope) !== scopeKey(state.scope))
        throw new ContractError('FETCH_SCOPE_MISMATCH');
    if (options.applicationEmbedding && scopeKey(options.applicationEmbedding.context.document.scope) !== scopeKey(state.scope))
        throw new ContractError('APPLICATION_SCOPE_MISMATCH');
    if (options.applicationEmbedding) {
        const s = options.applicationEmbedding.context.document.scope;
        if (s.epoch !== state.authority.epoch || s.controlHead !== state.authority.controlHead)
            throw new ContractError('APPLICATION_AUTHORITY_MISMATCH');
        options.applicationEmbedding.assertViewAvailable();
    }
    let applicationInvalidation = null;
    let alive = true, session = null, version = 0, loaded = null;
    let saved = null, storageBusy = false, storageBlocked = false, storageMessage = '', pendingDraft = null;
    let sessionGeneration = 0;
    const sent = new Set();
    const prefix = 'par-note-' + (++instance);
    const document = root.ownerDocument;
    function text(key) { return words[key][locale === 'ja' ? 0 : 1]; }
    function el(tag, cls = '', value = '') { const x = document.createElement(tag); if (cls)
        x.className = cls; x.textContent = value; return x; }
    function button(value) { const b = el('button', 'par-button', value); b.type = 'button'; return b; }
    const panel = el('section', 'par-note');
    panel.setAttribute('aria-label', text('title'));
    const top = el('header', 'par-note-heading'), heading = el('h1'), detailsButton = button(text('details'));
    heading.id = prefix + '-title';
    top.append(heading, detailsButton);
    panel.append(top);
    const primary = el('p', 'par-primary');
    primary.dataset.test = 'primary';
    primary.setAttribute('role', 'status');
    panel.append(primary);
    const summary = el('dl', 'par-summary');
    const fields = ['snapshot', 'copies', 'connection'];
    const labels = [], values = [];
    for (const field of fields) {
        const wrapper = el('div'), label = el('dt', '', text(field)), value = el('dd');
        labels.push(label);
        values.push(value);
        wrapper.append(label, value);
        summary.append(wrapper);
    }
    panel.append(summary);
    const form = el('div', 'par-edit');
    const label = el('label', 'par-label', text('body'));
    label.htmlFor = prefix + '-body';
    const area = el('textarea', 'par-editor');
    area.id = label.htmlFor;
    area.dataset.test = 'editor';
    area.value = draft.text;
    area.spellcheck = false;
    const localTitle = el('h2', 'par-private-title', text('privateTitle'));
    const privateStatus = el('p', 'par-private-status');
    privateStatus.id = prefix + '-private';
    privateStatus.setAttribute('role', 'status');
    area.setAttribute('aria-describedby', privateStatus.id);
    const saveButton = button(text('save')), restoreButton = button(text('restore')), inspectButton = button(text('inspect'));
    saveButton.dataset.test = 'private-save';
    restoreButton.dataset.test = 'private-restore';
    inspectButton.dataset.test = 'private-inspect';
    const privateButtons = el('div', 'par-buttons');
    privateButtons.append(saveButton, restoreButton, inspectButton);
    const localHelp = el('p', 'par-hint', text('localOnly'));
    form.append(label, area, localTitle, privateStatus, privateButtons, localHelp);
    panel.append(form);
    const effects = el('section', 'par-effects');
    const actionTitle = el('h2', '', text('actions'));
    const actions = el('div', 'par-buttons');
    const actionResult = el('p', 'par-hint');
    actionResult.dataset.test = 'effect-result';
    actionResult.setAttribute('role', 'status');
    effects.append(actionTitle, actions, actionResult);
    panel.append(effects);
    const details = el('section', 'par-details');
    details.id = prefix + '-details';
    details.hidden = true;
    const detailHeading = el('h2', '', text('details')), detailBody = el('pre');
    details.append(detailHeading, detailBody);
    detailsButton.setAttribute('aria-controls', details.id);
    detailsButton.setAttribute('aria-expanded', 'false');
    panel.append(details);
    const dialog = el('dialog', 'par-dialog');
    dialog.dataset.test = 'confirmation';
    const dialogTitle = el('h2', '', text('review'));
    dialogTitle.id = prefix + '-review';
    dialog.setAttribute('aria-labelledby', dialogTitle.id);
    const dialogBody = el('p');
    const confirmLabel = el('label', 'par-confirm');
    const checkBox = el('input');
    checkBox.type = 'checkbox';
    const checkText = el('span', '', text('check'));
    confirmLabel.append(checkBox, checkText);
    const confirm = button(text('confirm')), cancel = button(text('cancel'));
    const dialogButtons = el('div', 'par-buttons');
    dialogButtons.append(cancel, confirm);
    dialog.append(dialogTitle, dialogBody, confirmLabel, dialogButtons);
    panel.append(dialog);
    const disclaimer = el('p', 'par-disclaimer', text('synthetic'));
    panel.append(disclaimer);
    root.replaceChildren(panel);
    const fetchRoot = options.fetchOwner ? el('div', 'par-fetch-owner') : null;
    if (fetchRoot)
        panel.append(fetchRoot);
    const fetchControls = fetchRoot && options.fetchOwner ? mountFetchControls(fetchRoot, options.fetchOwner, locale) : null;
    const applicationRoot = options.applicationEmbedding ? el('div', 'par-application-owner') : null;
    if (applicationRoot)
        panel.append(applicationRoot);
    const applicationControls = applicationRoot && options.applicationEmbedding ? mountApplicationControls(applicationRoot, options.applicationEmbedding, locale) : null;
    let approve = null;
    let opener = null;
    function finishDialog() { if (dialog.open)
        dialog.close(); approve = null; const target = opener?.isConnected ? opener : detailsButton; target.focus(); }
    cancel.onclick = finishDialog;
    dialog.addEventListener('cancel', () => { approve = null; });
    dialog.addEventListener('close', () => { if (alive)
        (opener?.isConnected ? opener : detailsButton).focus(); });
    checkBox.onchange = () => { confirm.disabled = !checkBox.checked; };
    confirm.onclick = () => { if (!checkBox.checked || !approve)
        return; const f = approve; approve = null; finishDialog(); f(); };
    function ask(body, source, fn) { opener = source; approve = fn; dialogBody.textContent = body; checkBox.checked = false; confirm.disabled = true; dialog.showModal(); cancel.focus(); }
    function revealDetails() { details.hidden = !details.hidden; detailsButton.setAttribute('aria-expanded', String(!details.hidden)); }
    detailsButton.onclick = revealDetails;
    function actionKey(a) { return state.revision + '|' + a.kind + '|' + canonical(state.previews.find(p => p.kind === a.kind) ?? null); }
    async function dispatch(a, c, key) {
        if (sent.has(key))
            return;
        let intent;
        try {
            intent = prepareCommand(state, c);
        }
        catch {
            actionResult.textContent = text('stale');
            return;
        }
        if (!options.effectPort) {
            actionResult.textContent = text('unavailable');
            return;
        }
        sent.add(key);
        render();
        try {
            const r = await options.effectPort(intent);
            if (alive) {
                if (r.outcome === 'observed') {
                    applyUpdate(r.observation);
                    actionResult.textContent = text('observed');
                }
                else
                    actionResult.textContent = text(r.outcome === 'accepted' ? 'accepted' : r.outcome === 'unavailable' ? 'unavailable' : 'unknown');
            }
        }
        catch {
            if (alive)
                actionResult.textContent = text('unknown');
        }
    }
    function renderActions(vm) {
        actions.replaceChildren();
        for (const a of vm.actions) {
            const b = button(formatMessage({ key: 'action.' + a.kind, args: {} }, locale));
            b.dataset.command = a.kind;
            const key = actionKey(a);
            const missing = a.kind !== 'open-details' && !options.effectPort;
            b.disabled = !a.enabled || missing || sent.has(key);
            const wrapper = el('div', 'par-action');
            wrapper.append(b);
            if (!a.enabled || missing) {
                const reason = el('p', 'par-hint', missing ? text('unavailable') : (a.disabledReason ? formatMessage({ key: a.disabledReason, args: {} }, locale) : text('stale')));
                reason.id = prefix + '-' + a.kind + '-reason';
                b.setAttribute('aria-describedby', reason.id);
                wrapper.append(reason);
            }
            b.onclick = () => {
                if (a.kind === 'open-details') {
                    revealDetails();
                    return;
                }
                const command = { schemaVersion: 1, kind: a.kind, expectedRevision: state.revision, streamId: state.streamId, sequence: state.sequence, scope: clone(state.scope), operationId: a.kind === 'inspect-operation' ? (state.surface === 'rpc' ? state.rpc.operationId : state.local.operationId) : 'ui-' + newId(), confirmation: a.confirmation === 'none' ? null : clone(state.previews.find(p => p.kind === a.kind) ?? null) };
                const invoke = () => { void dispatch(a, command, key); };
                if (a.confirmation === 'none')
                    invoke();
                else
                    ask([command.confirmation?.target, command.confirmation?.impact, command.confirmation?.planDigest].filter(Boolean).join('\n'), b, invoke);
            };
            actions.append(wrapper);
        }
    }
    function render() {
        if (!alive)
            return;
        const vm = presentEditor(state, draft);
        heading.textContent = vm.document.title || text('title');
        primary.textContent = formatMessage(vm.primary, locale);
        values[0].textContent = formatMessage(vm.local.message, locale);
        values[1].textContent = formatMessage(vm.protection.message, locale);
        values[2].textContent = formatMessage(vm.connection.message, locale);
        fields.forEach((f, i) => { labels[i].textContent = text(f === 'snapshot' && state.evidence.kind === 'runtime-observation' ? 'snapshotRuntime' : f); });
        label.textContent = text('body');
        detailsButton.textContent = text('details');
        detailHeading.textContent = text('details');
        localTitle.textContent = text('privateTitle');
        actionTitle.textContent = text('actions');
        saveButton.textContent = text('save');
        restoreButton.textContent = text('restore');
        inspectButton.textContent = text('inspect');
        localHelp.textContent = text('localOnly');
        disclaimer.textContent = text(state.evidence.kind === 'runtime-observation' ? 'runtime' : 'synthetic');
        dialogTitle.textContent = text('review');
        checkText.textContent = text('check');
        cancel.textContent = text('cancel');
        confirm.textContent = text('confirm');
        privateStatus.textContent = storageMessage || (session ? (saved === fingerprint(draft) ? text('saved') : loaded?.draft ? text('storedOther') : text('unsaved')) : text('volatile'));
        saveButton.disabled = !session || storageBusy || storageBlocked || draft.composing || state.scope.documentId === null;
        restoreButton.hidden = !loaded?.draft;
        restoreButton.disabled = storageBusy || draft.composing;
        inspectButton.hidden = !storageBlocked;
        inspectButton.disabled = storageBusy;
        detailBody.textContent = JSON.stringify({ scope: state.scope, revision: state.revision, frontier: state.document.frontier, controlHead: state.authority.controlHead, epoch: state.authority.epoch, observedAt: state.snapshotTime, evidence: state.evidence, crdtApplied: state.document.applied, privateDraftVersion: version, sharedSavedByThisUI: false }, null, 2);
        renderActions(vm);
    }
    function ingest() { try {
        draft = reduceDraft(draft, { type: 'input', text: area.value, anchor: area.selectionStart, focus: area.selectionEnd });
        storageMessage = '';
        render();
    }
    catch (e) {
        privateStatus.textContent = e instanceof ContractError ? e.code : 'INVALID_INPUT';
    } }
    area.addEventListener('input', ingest);
    area.addEventListener('compositionstart', () => { draft = reduceDraft(draft, { type: 'composition-start' }); render(); });
    area.addEventListener('compositionend', () => { ingest(); draft = reduceDraft(draft, { type: 'composition-end' }); render(); });
    area.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        if (!saveButton.disabled)
            saveButton.click();
    } });
    saveButton.onclick = async () => {
        if (!session || storageBusy || storageBlocked || draft.composing)
            return;
        const localSession = session, at = sessionGeneration;
        pendingDraft = clone(draft);
        const captured = pendingDraft;
        storageBusy = true;
        storageMessage = text('saving');
        render();
        const op = 'draft-' + newId(), expected = version;
        try {
            const receipt = checkDraftReceipt(await localSession.save(captured, expected, op), expected, op);
            if (!alive || at !== sessionGeneration)
                return;
            version = receipt.version;
            saved = fingerprint(captured);
            loaded = { version, operationId: receipt.operationId, draft: captured };
            storageMessage = '';
            pendingDraft = null;
        }
        catch (e) {
            if (!alive || at !== sessionGeneration)
                return;
            storageBlocked = true;
            const conflict = e.code === 'DRAFT_CONFLICT';
            storageMessage = text(conflict ? 'conflict' : 'unknown');
            if (conflict) {
                try {
                    const found = checkDraftLoad(await localSession.load());
                    if (alive && at === sessionGeneration)
                        loaded = found;
                }
                catch { /* Keep the editor blocked; never overwrite an unverified draft. */ }
            }
        }
        finally {
            if (alive && at === sessionGeneration) {
                storageBusy = false;
                render();
            }
        }
    };
    restoreButton.onclick = () => {
        if (!loaded?.draft || draft.composing)
            return;
        const current = loaded;
        ask(text('replace'), restoreButton, () => {
            if (!current.draft)
                return;
            draft = restoreDraft(current.draft, state);
            area.value = draft.text;
            area.setSelectionRange(draft.selection.anchor, draft.selection.focus);
            saved = fingerprint(current.draft);
            version = current.version;
            storageBlocked = false;
            storageMessage = '';
            render();
            area.focus();
        });
    };
    inspectButton.onclick = async () => {
        if (!session || storageBusy)
            return;
        storageBusy = true;
        render();
        try {
            const outcome = await session.reconcile();
            if (!alive)
                return;
            const current = checkDraftLoad(await session.load());
            if (!alive)
                return;
            loaded = current;
            version = current.version;
            if (outcome === 'CONFIRMED' && pendingDraft)
                saved = fingerprint(pendingDraft);
            storageMessage = outcome === 'CONFIRMED' ? '' : outcome === 'SUPERSEDED' ? text('conflict') : text('notConfirmed');
            storageBlocked = outcome === 'SUPERSEDED';
            pendingDraft = null;
        }
        catch {
            if (alive)
                storageMessage = text('unknown');
        }
        finally {
            if (alive) {
                storageBusy = false;
                render();
            }
        }
    };
    async function attachDraftSession(next) {
        checkScope(next.scope);
        if (scopeKey(next.scope) !== scopeKey(state.scope))
            throw new Error('DRAFT_SCOPE_MISMATCH');
        if (storageBusy)
            throw new Error('DRAFT_BUSY');
        const at = ++sessionGeneration;
        session?.close();
        session = null;
        storageBusy = true;
        render();
        try {
            const found = checkDraftLoad(await next.load());
            if (!alive || at !== sessionGeneration) {
                next.close();
                return;
            }
            loaded = found;
            version = found.version;
            session = next;
            storageBlocked = false;
            storageMessage = '';
            saved = found.draft ? fingerprint(found.draft) : null;
        }
        catch (e) {
            next.close();
            storageMessage = e.code ?? 'DRAFT_UNAVAILABLE';
            throw e;
        }
        finally {
            if (alive && at === sessionGeneration) {
                storageBusy = false;
                render();
            }
        }
    }
    render();
    if (options.draftSession)
        void attachDraftSession(options.draftSession).catch(() => { });
    function applyUpdate(next) {
        if (!alive)
            throw new Error('VIEW_CLOSED');
        const old = state;
        state = advanceSnapshot(state, next);
        if (options.applicationEmbedding && (state.authority.epoch !== old.authority.epoch || state.authority.controlHead !== old.authority.controlHead || state.authority.state !== old.authority.state)) {
            applicationInvalidation = options.applicationEmbedding.invalidate();
            void applicationInvalidation.catch(() => { });
        }
        if (state.authority.epoch !== old.authority.epoch || state.authority.controlHead !== old.authority.controlHead || state.authority.sharedWriteAllowed !== old.authority.sharedWriteAllowed)
            draft = reduceDraft(draft, { type: 'authority-changed' });
        if (state.document.frontier !== old.document.frontier || state.document.text !== old.document.text) {
            draft = reduceDraft(draft, { type: 'remote', text: state.document.text, frontier: state.document.frontier, sequence: state.sequence });
            if (!draft.dirty && !draft.composing && !draft.requiresRebase) {
                draft = reduceDraft(draft, { type: 'accept-remote' });
                area.value = draft.text;
            }
        }
        render();
    }
    return {
        update: applyUpdate, getDraft() { return clone(draft); }, setLocale(next) { locale = next; fetchControls?.setLocale(next); applicationControls?.setLocale(next); render(); }, attachDraftSession,
        applicationCleanup() { return applicationInvalidation ?? applicationControls?.cleanup() ?? Promise.resolve(); },
        destroy() { alive = false; applicationControls?.destroy(); fetchControls?.destroy(); sessionGeneration++; session?.close(); if (dialog.open)
            dialog.close(); root.replaceChildren(); }
    };
}
