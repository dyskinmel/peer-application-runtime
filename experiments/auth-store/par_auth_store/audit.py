"""Corruption checks against signed history and local commit bindings.

Digests do not defend against an attacker rewriting the entire SQLite DB. A
separately trusted head/pin is required to detect whole-DB rollback.
"""
from par_store.store import Store
from par_store.model import from_u64
from par_wire.codec import decode
from par_crypto.primitives import hashed
from par_crypto import objects
from par_auth.membership import member_certificate
from .model import proof_hash

PROOF_FIELDS=['operation_id','space_id','head','sequence','epoch','revision','device_id','certificate','key_check','material_id','prepared_digest']

def audit(owner):
    base=Store.audit(owner._storage);errors=list(base['errors']);c=owner._storage.connection;states={}
    try:
        c.execute('BEGIN')
        spaces={r[0] for r in c.execute('SELECT space_id FROM spaces')}
        authspaces={r[0] for r in c.execute('SELECT space_id FROM auth_spaces')}
        if spaces!=authspaces:errors.append('AUTH_SPACE_SET')
        for space in authspaces:
            row,st=owner._load(space);states[space]=(row,st)
        n=c.execute('SELECT count(*) FROM auth_commits').fetchone()[0]
        if n!=c.execute('SELECT count(*) FROM commit_ledger').fetchone()[0]:errors.append('AUTH_COMMIT_SET')
        for r in c.execute('SELECT * FROM auth_commits'):
            vals=tuple(r[k] for k in PROOF_FIELDS)
            if proof_hash(vals)!=r['proof_digest']:errors.append('AUTH_PROOF_DIGEST');continue
            row,st=states[r['space_id']];node=st.control(r['head']);cert=member_certificate(owner._provider,st.app_id,st.membership_at(node.id),r['certificate'])
            did=hashed('device-id',[st.app_id,cert[3]])
            if did!=r['device_id'] or st.membership_at(node.id).get(did).role!=2:errors.append('AUTH_PROOF_ROLE')
            if node.body[2]!=from_u64(r['sequence']) or node.body[3]!=from_u64(r['epoch']) or from_u64(r['revision'])>from_u64(row['revision']):errors.append('AUTH_PROOF_HEAD')
            material=c.execute('SELECT * FROM auth_materials WHERE space_id=? AND material_id=?',(r['space_id'],r['material_id'])).fetchone()
            if material is None or (material['epoch'],material['anchor'],material['key_check'])!=(r['epoch'],node.anchor_id,r['key_check']):errors.append('AUTH_PROOF_MATERIAL')
            rec=c.execute('''SELECT m.prepared_digest,e.encrypted_bytes,e.state FROM commit_ledger l
              JOIN local_commit_meta m USING(operation_id) JOIN envelopes e ON e.envelope_id=l.commit_id WHERE l.operation_id=?''',(r['operation_id'],)).fetchone()
            if rec is None or rec['prepared_digest']!=r['prepared_digest'] or rec['state']!='pending':errors.append('AUTH_PAYLOAD_BINDING');continue
            envelope=decode(rec['encrypted_bytes']);header=decode(envelope[0]);objects.change_header(header)
            if (header[0],header[1],header[2],header[5],header[13])!=(st.app_id,st.space_id,from_u64(r['epoch']),r['device_id'],r['head']):errors.append('AUTH_HEADER_BINDING')
            _signature(owner._provider,cert[3],envelope)
    except Exception:errors.append('AUTH_STORE_CORRUPT')
    finally:
        if c.in_transaction:c.execute('ROLLBACK')
    return {'valid':not errors,'errors':sorted(set(errors)),'scope':'SIGNED_KNOWN_AUTHORITY_AND_LOCAL_ATOMIC_BINDINGS',
            'automerge_validated':False,'global_latest_proven':False,'hostile_db_rollback_protected':False}

def _signature(provider,public,o):
    from par_crypto.primitives import domain
    provider.verify(public,domain('envelope-sign',[o[0],o[1],o[2]]),o[3])
