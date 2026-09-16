"""Bounded dependency extraction from the authenticated local Store, read-only.

Old synthetic records are NOT automatically declared Automerge-valid: the core
must revalidate every returned inner change on an isolated document.
"""
from par_wire.codec import decode
from par_crypto import objects
from par_auth.membership import member_certificate
from par_store.model import u64
from .contracts import ChangeInput, Dependency, MAX_CLOSURE, MAX_CLOSURE_BYTES, SharedChangeError, require


def stamp(owner, space):
    c=owner._storage.connection
    return (c.total_changes,c.execute('PRAGMA data_version').fetchone()[0],
            c.execute('PRAGMA schema_version').fetchone()[0],owner.pin(space),owner.status(space))


def collect_dependencies(owner, candidate: ChangeInput, epoch_secret: bytes, *, schema_id: bytes):
    owner._enter();h=candidate.header;before=stamp(owner,h[1]);c=owner._storage.connection
    require(owner.audit()['valid'],'STORE_VERIFICATION_FAILED')
    _,state=owner._load(h[1]);found={};visiting=set();ordered=[];total=len(candidate.payload)
    def visit(cid):
        nonlocal total
        require(cid not in visiting,'DEPENDENCY_CYCLE')
        if cid in found:return
        require(len(found)+len(visiting)<MAX_CLOSURE,'RESOURCE_LIMIT')
        rows=list(c.execute('''SELECT e.envelope_id,e.encrypted_bytes,a.certificate,a.head FROM envelopes e
          JOIN commit_ledger l ON l.commit_id=e.envelope_id JOIN auth_commits a USING(operation_id)
          WHERE e.space_id=? AND e.object_id=? AND e.epoch=? AND e.change_hash=? LIMIT 2''',
          (h[1],h[3],u64(h[2]),cid)))
        require(len(rows)!=0,'DEPENDENCIES_MISSING');require(len(rows)==1,'DEPENDENCY_EQUIVOCATION')
        row=rows[0]
        try:
            env=decode(row['encrypted_bytes']);dh=decode(env[0]);
            cert=member_certificate(owner._provider,state.app_id,state.membership_at(row['head']),row['certificate'])
            plain=objects.open_change(owner._provider,epoch_secret,cert[3],dh,row['encrypted_bytes'])
            require(objects.envelope_id(row['encrypted_bytes'])==row['envelope_id'],'STORE_VERIFICATION_FAILED')
            item=ChangeInput.create(dh,plain,schema_id=schema_id)
            require(item.header[12]==cid,'STORE_VERIFICATION_FAILED')
        except SharedChangeError:raise
        except Exception:raise SharedChangeError('STORE_VERIFICATION_FAILED') from None
        total+=len(plain);require(total<=MAX_CLOSURE_BYTES,'RESOURCE_LIMIT')
        visiting.add(cid)
        for parent in sorted(item.header[10]):visit(parent)
        visiting.remove(cid);dep=Dependency(bytes(row['envelope_id']),item);found[cid]=dep;ordered.append(dep)
    for cid in sorted(h[10]):visit(cid)
    require(before==stamp(owner,h[1]),'OWNER_STATE_CHANGED')
    return tuple(ordered)
