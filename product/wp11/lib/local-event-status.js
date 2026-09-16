import { canonical, check, freeze, record } from './validate.js';
const messages = {
    idle: ['イベント操作はありません。接続は明示的に行ってください。', 'No event operation. Connect explicitly.'],
    publishing: ['ローカルイベントを送信中です。保存結果はまだ未確認です。', 'Sending a local event. Its storage outcome is not confirmed.'],
    inquiring: ['元の操作IDでローカルイベントの結果を照会中です。', 'Inquiring about the local event using its original operation ID.'],
    'outcome-unknown': ['保存結果は不明です。元の操作IDを保持し、明示的に接続・照会してください。', 'The storage outcome is unknown. Retain the original operation ID and reconnect/inquire explicitly.'],
    'inquiry-failed': ['照会を完了できませんでした。不在とは判断しません。', 'The inquiry could not be completed. This does not mean the event is absent.'],
    'not-found-local': ['今回の照会ではイベントを確認できません。未実行や再送の安全性は確認できません。', 'This inquiry did not find the event locally. Non-execution and safe replay are not established.'],
    'local-committed': ['ローカルイベントの保存を確認しました。共有文書の保存や他端末での保管は未確認です。', 'A local event receipt was observed. This is not a shared document commit or remote retention proof.'],
    cancelled: ['イベント操作は取り消されました。取消しの段階は操作結果で確認してください。', 'The event operation was cancelled. Inspect the result for its cancellation phase.'],
    rejected: ['イベント操作は拒否されました。安定エラーコードを確認してください。', 'The event operation was rejected. Inspect its stable error code.'],
};
export function presentLocalEventClient(client, expectedContext, locale) {
    check(locale === 'ja' || locale === 'en', 'locale');
    const state = client.current, expected = expectedContext;
    // Type-only SDK coupling keeps the reference app build independently portable.
    // Exact validated client context is the comparison value, not a wire assertion.
    record(expected, ['protocol', 'appId', 'spaceId', 'streamId', 'epoch', 'schema', 'schemaDigest', 'issuer', 'journalGeneration', 'authority']);
    check(expected.schema !== null && typeof expected.schema === 'object', 'schema');
    record(expected.schema, Object.keys(expected.schema));
    check(canonical(state.context) === canonical(expected), 'event scope', 'LOCAL_EVENT_CONTEXT_MISMATCH');
    const view = client.view, index = locale === 'ja' ? 0 : 1;
    // Both accessors are synchronous and invoke no transport/await/user callback.
    let message = messages[state.operation.kind][index];
    if (state.cleanup.failed)
        message = ['以前の接続の解放を確認できません。接続の所有者を確認してください。', 'Previous connection cleanup is unconfirmed. Inspect the connection owner.'][index];
    else if (state.connection === 'closed')
        message = ['イベント接続は閉じています。過去の保存結果を現在の接続確認とは扱いません。', 'The event client is closed. A historical receipt is not evidence of a current connection.'][index];
    return freeze({ profile: 'par-reference-local-event-status-0041', scope: { appId: expected.appId, spaceId: expected.spaceId, streamId: expected.streamId },
        revision: state.revision, bindingGeneration: state.bindingGeneration, operationId: view.operationId,
        connection: state.connection, outcome: state.operation.kind, message, problemCode: view.problemCode,
        eventSequence: state.knownCommit?.sequence ?? null, localReceiptPreviouslyObserved: state.knownCommit !== null,
        controls: { publish: view.canPublish, inquire: view.canInquire, rebind: view.needsRebind && !state.cleanup.failed },
        sharedCommit: false, remoteProtection: false, automaticRetry: false, productQualified: false });
}
