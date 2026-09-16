"""Collect a current-epoch closure from a cooperative BlobStore read transaction.

The caller supplies an ALREADY issued recipient key package. The collector never
mints identity, membership, control history or a recipient's key distribution.
"""
from __future__ import annotations
from par_wire.codec import decode
from par_crypto import objects
from par_crypto.primitives import hashed
from par_auth.membership import member_certificate
from par_store.model import from_u64
from .contract import *
from .graph import closure
from .errors import RecoveryError as E

def collect(store,space,roots,grant,certificate,signing_seed):
    try:
        if type(roots) is not tuple or not 1<=len(roots)<=MAX_ENVELOPES or len(set(roots))!=len(roots):raise E('ROOT_SET')
        for x in roots:fixed(x)
        if type(grant) is not Grant:raise E('GRANT_INVALID')
        fixed(space);fixed(signing_seed)
        # Freeze borrowed containers/bytes before reading source state.
        recipient_cert=bytes(grant.certificate);package=bytes(grant.package)
        seed_manifest=bytes(grant.seed_manifest);pids=list(grant.package_ids);seed_items=list(grant.seeds)
        ordered_ids(pids,1024,True)
        if any(type(i) is not tuple or len(i)!=2 for i in seed_items):raise E('GRANT_INVALID')
        seeds=dict(seed_items)
        if len(seeds)!=len(seed_items):raise E('GRANT_INVALID')
        store._enter()
        if space in store._failed:raise E('AUTH_PERSISTENCE_UNCERTAIN')
        if not store.audit()['valid']:raise E('SOURCE_CORRUPT')
        c=store._storage.connection;c.execute('BEGIN')
        try:
            row,st=store._load(space);st._blocked();members=st.membership
            cert=member_certificate(store._provider,st.app_id,members,certificate)
            did=hashed('device-id',[st.app_id,cert[3]])
            if members.get(did).role!=2:raise E('NOT_AUTHORIZED')
            if store._provider.sign_public(signing_seed)!=cert[3]:raise E('SIGNER_MISMATCH')
            rc=member_certificate(store._provider,st.app_id,members,recipient_cert)
            rid=hashed('device-id',[st.app_id,rc[3]])
            if members.get(rid).role not in (1,2):raise E('NOT_AUTHORIZED')
            # Bounded scan; do not pretend a truncated scan is a complete dependency index.
            rawmap={};headers={};scanned_bytes=0
            for eid,raw in c.execute('SELECT envelope_id,encrypted_bytes FROM envelopes WHERE space_id=? LIMIT 4097',(space,)):
                scanned_bytes+=len(raw)
                if len(rawmap)>=4096 or scanned_bytes>MAX_BYTES:raise E('SOURCE_INDEX_LIMIT')
                rawmap[eid]=raw;headers[eid]=decode(decode(raw)[0])
            selected=closure(roots,headers)
            if any(headers[i][2]!=st.epoch for i in selected):raise E('EPOCH_UNSUPPORTED')
            data={};types={};total=0
            def add(kind,raw):
                nonlocal total
                bounded(raw);oid=object_id(kind,raw)
                if oid in data:
                    if data[oid]!=raw or types[oid]!=kind:raise E('OBJECT_HASH')
                    return oid
                total+=len(raw)
                if total>MAX_BYTES or len(data)>=MAX_OBJECTS:raise E('CLOSURE_LIMIT')
                data[oid]=raw;types[oid]=kind;return oid
            replay=add('replay',row['replay']);receiver=add('certificate',recipient_cert);issuer=add('certificate',certificate)
            g={0:1,1:add('package',package),2:pids,3:add('seed-manifest',seed_manifest),4:[[bid,add('seed',raw)] for bid,raw in sorted(seeds.items())]}
            grant_id=add('grant',dumps(g));entries=[]
            for eid in sorted(selected):
                raw=rawmap[eid];h=headers[eid]
                rec=c.execute('SELECT certificate FROM auth_commits WHERE operation_id=(SELECT operation_id FROM commit_ledger WHERE commit_id=?)',(eid,)).fetchone()
                if rec is None:raise E('SOURCE_CORRUPT')
                ar=c.execute('SELECT mode,manifest FROM blob_commit_roots WHERE envelope_id=?',(eid,)).fetchone()
                if ar is None:raise E('SOURCE_CORRUPT')
                blocks=[]
                for r in c.execute('SELECT block_id FROM envelope_blocks WHERE envelope_id=? ORDER BY position',(eid,)):
                    blocks.append(add('block',store._storage.read_block(r[0])))
                entries.append({0:eid,1:add('envelope',raw),2:add('certificate',rec[0]),3:add('attachment',ar[1]) if ar[0] else None,4:blocks})
            body={0:1,1:'recovery-closure-local',2:st.app_id,3:space,4:st.head,5:st.sequence,6:st.epoch,7:rid,8:objects.certificate_id(recipient_cert),9:sorted(roots),10:replay,11:receiver,12:grant_id,13:issuer,14:entries,15:[[oid,types[oid],len(data[oid])] for oid in sorted(data)]}
            raw=sign_index(store._provider,signing_seed,body)
        finally:
            if c.in_transaction:c.execute('ROLLBACK')
        bundle=Bundle(raw,data)
        # A local consistency check; returned pin is NOT a substitute for trusted delivery.
        from .verify import verify_public
        pin=Pin(body[2],body[3],body[4],body[5],body[6],body[7],body[8],tuple(body[9]),index_id(raw))
        verify_public(bundle,pin,store._provider)
        return bundle
    except E:raise
    except Exception as ex:
        code=getattr(ex,'code',None)
        if code=='NOT_AUTHORIZED':raise E('NOT_AUTHORIZED') from None
        raise E('COLLECT_INVALID') from None
