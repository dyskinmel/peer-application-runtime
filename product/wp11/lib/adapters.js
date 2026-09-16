import { validateState, record, check, count, list, string, clone } from './validate.js';
/**
 * Version-specific DISPLAY adapter for an already-verified local RecoveryView report.
 * JSON booleans are not cryptographic proof. This adapter performs no authentication,
 * materialization, file IO or effect. Caller supplies the expected scope/root/sequence.
 */
export function adaptRecoveryStatus(context, input) {
    const s = clone(validateState(context));
    check(input !== null && typeof input === 'object', 'recovery report');
    const sd = Object.getOwnPropertyDescriptor(input, 'state');
    check(sd && 'value' in sd, 'report state');
    let phase, verified = false, missing = '0';
    if (sd.value === 'RECIPIENT_VALIDATED_READ_ONLY') {
        const r = record(input, ['state', 'objects_complete', 'signed_history_verified', 'recipient_authorized', 'payloads_decrypted', 'whole_files_verified', 'envelopes', 'roots', 'seed_semantics', 'inner_validated', 'applied', 'writable', 'global_latest_proven', 'network_verified', 'product_qualified']);
        for (const k of ['objects_complete', 'signed_history_verified', 'recipient_authorized', 'payloads_decrypted'])
            check(r[k] === true, 'incomplete recipient observation');
        for (const k of ['inner_validated', 'applied', 'writable', 'global_latest_proven', 'network_verified', 'product_qualified'])
            check(r[k] === false, 'unsupported claim');
        check(r.seed_semantics === 'OPAQUE_BYTES', 'seed semantics');
        count(r.whole_files_verified, 64);
        count(r.envelopes, 64);
        list(r.roots, 64, v => { string(v, 64); check(/^[0-9a-f]{64}$/.test(v), 'root hex'); });
        check(r.roots.includes(s.protection.root), 'root mismatch');
        phase = 'read-only';
        verified = true;
    }
    else {
        const r = record(input, ['state', 'missing', 'recipient_validated', 'applied', 'product_qualified']);
        check(r.state === 'MISSING_OBJECTS' || r.state === 'BYTES_COMPLETE', 'report state');
        for (const k of ['recipient_validated', 'applied', 'product_qualified'])
            check(r[k] === false, 'unsupported claim');
        list(r.missing, 1024, v => { string(v, 64); check(/^[0-9a-f]{64}$/.test(v), 'object hex'); });
        check((r.state === 'BYTES_COMPLETE') === (r.missing.length === 0), 'inconsistent missing set');
        check(new Set(r.missing).size === r.missing.length, 'duplicate missing ID');
        phase = r.state === 'BYTES_COMPLETE' ? 'verifying' : 'partial';
        missing = String(r.missing.length);
    }
    // Opaque change bytes are not a rendered document, nor a local commit receipt.
    return validateState({ ...s, surface: 'recovery', local: { ...s.local, state: 'unknown', operationId: null },
        document: { ...s.document, read: 'waiting-data', text: '', title: '', innerValidated: false, applied: false, knownCatalogComplete: false, missingObjects: missing },
        authority: { ...s.authority, sharedWriteAllowed: false },
        recovery: { phase, received: '0', total: null, recipientValidated: verified, keys: verified ? 'available' : s.recovery.keys, missingObjects: missing },
        evidence: { kind: 'runtime-observation', references: s.evidence.references } });
}
