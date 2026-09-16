/** Input is a trusted, immutable client snapshot, not unvalidated network JSON.
 * No payload, note text, parent bytes or authority upgrade cross this projection.
 */
export function projectEventClient(state) {
    const connected = state.connection === 'connected' && !state.cleanup.failed;
    const busy = state.operation.kind === 'publishing' || state.operation.kind === 'inquiring';
    const operationId = 'operationId' in state.operation ? state.operation.operationId : null;
    return Object.freeze({ profile: 'par-local-event-client-view-0041', revision: state.revision,
        bindingGeneration: state.bindingGeneration, connection: state.connection, status: state.operation.kind,
        operationId, problemCode: 'code' in state.operation ? state.operation.code : null, localReceipt: state.knownCommit,
        canPublish: connected && !busy && !state.requiresInquiry && state.context.authority === 'owner-publish',
        canInquire: connected && !busy && operationId !== null, needsRebind: state.connection === 'unbound' || state.connection === 'rebind-required',
        requiresInquiry: state.requiresInquiry, cleanupFailed: state.cleanup.failed,
        sharedCommit: false, remoteProtection: false, automaticRetry: false });
}
