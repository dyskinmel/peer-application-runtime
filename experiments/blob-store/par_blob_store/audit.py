"""Reconstruct exact reference sets and verify author signatures, not just counts."""
from par_auth_store.audit import audit as auth_audit
from par_store.model import PreparedCommit,from_u64
from par_wire.codec import decode
from par_auth.membership import member_certificate
from .model import Attachment, inspect_attachment, inspect_batch, verify_manifest
from .store import binding_row, BIND_COLUMNS

def audit(owner):
    base=auth_audit(owner);errors=list(base['errors']);c=owner._storage.connection
    try:
        c.execute('BEGIN')
        ledgers={r['operation_id']:r for r in c.execute('SELECT * FROM commit_ledger')}
        roots={r['operation_id']:r for r in c.execute('SELECT * FROM blob_commit_roots')}
        if set(ledgers)!=set(roots):errors.append('BLOB_ROOT_SET')
        expected_objects=set();expected_refs=set()
        for op,l in ledgers.items():
            root=roots.get(op)
            if root is None:continue
            eid=l['commit_id']
            if root['envelope_id']!=eid:errors.append('BLOB_ROOT_BINDING')
            rows=list(c.execute('SELECT block_id,position FROM envelope_blocks WHERE envelope_id=? ORDER BY position',(eid,)))
            refs=list(c.execute('SELECT typed_id,position FROM blob_references WHERE envelope_id=? ORDER BY position',(eid,)))
            if root['mode']==0:
                if rows or refs or root['manifest'] is not None:errors.append('LEGACY_ATTACHMENTS')
                continue
            if [r['position'] for r in rows]!=list(range(len(rows))) or [r['position'] for r in refs]!=list(range(len(rows))):errors.append('BLOB_POSITION_SET')
            attachments=[]
            for r in rows:
                raw=owner._storage.read_block(r['block_id']);outer=decode(raw)
                from par_crypto.objects import block_id
                a=Attachment(block_id(raw),outer[0],raw);b=inspect_attachment(a)
                row=c.execute('SELECT * FROM blob_objects WHERE typed_id=?',(b.typed_id,)).fetchone()
                if row is None or tuple(row[k] for k in BIND_COLUMNS)!=binding_row(b):errors.append('BLOB_ALIAS_BINDING')
                expected_objects.add(b.typed_id);expected_refs.add((eid,r['position'],b.typed_id));attachments.append(a)
            e=c.execute('SELECT * FROM envelopes WHERE envelope_id=?',(eid,)).fetchone()
            m=c.execute('SELECT * FROM local_commit_meta WHERE operation_id=?',(op,)).fetchone()
            p=PreparedCommit(op,l['input_digest'],e['space_id'],e['object_id'],e['actor_id'],m['actor_generation'],from_u64(e['epoch']),from_u64(e['sequence']),m['previous_envelope'],e['change_hash'],m['reservation_id'],e['encrypted_bytes'],m['encrypted_cache'],l['receipt_encrypted'],(),tuple(a.sealed_bytes for a in attachments))
            header=decode(decode(e['encrypted_bytes'])[0]);bindings=inspect_batch(tuple(attachments),header)
            proof=c.execute('SELECT * FROM auth_commits WHERE operation_id=?',(op,)).fetchone();_,st=owner._load(proof['space_id'])
            cert=member_certificate(owner._provider,st.app_id,st.membership_at(proof['head']),proof['certificate'])
            verify_manifest(owner._provider,cert[3],p,bindings,root['manifest'])
        actual_refs={(r[0],r[1],r[2]) for r in c.execute('SELECT envelope_id,position,typed_id FROM blob_references')}
        if actual_refs!=expected_refs:errors.append('BLOB_REFERENCE_SET')
        if {r[0] for r in c.execute('SELECT typed_id FROM blob_objects')}!=expected_objects:errors.append('BLOB_OBJECT_SET')
        if {r[0] for r in c.execute('SELECT locator FROM blob_objects')}!={r[0] for r in c.execute('SELECT block_id FROM blocks')}:errors.append('BLOB_LOCATOR_SET')
    except Exception:errors.append('BLOB_STORE_CORRUPT')
    finally:
        if c.in_transaction:c.execute('ROLLBACK')
    return {'valid':not errors,'errors':sorted(set(errors)),'scope':'LOCAL_SIGNED_ATTACHMENTS_AND_AUTHORIZED_REFERENCES',
            'aead_rechecked_on_read':True,'whole_blob_complete':False,'automerge_validated':False,
            'production_qualified':False,'hostile_db_rollback_protected':False}
