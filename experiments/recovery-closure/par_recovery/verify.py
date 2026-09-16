"""No success flag from a provider is trusted. Re-derive every reference and role."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from par_crypto import objects
from par_crypto.primitives import domain,hashed
from par_wire.codec import decode
from par_auth.membership import member_certificate
from par_auth.replay import restore_public_replay
from par_auth.activation import parse_seed_manifest
from par_auth.receiver import receive_change
from par_blob_store.model import Attachment,inspect_batch,verify_manifest
from .contract import *
from .graph import closure
from .errors import RecoveryError as E
@dataclass(frozen=True)
class AttachmentContext:
    space_id: bytes
    epoch: int
    object_id: bytes
    envelope_id: bytes
    envelope: bytes
@dataclass
class PublicSet:
    body: dict
    data: dict
    state: object
    recipient_certificate: bytes
    grant: dict
    seeds: dict
    bindings: dict
    plaintexts: dict
    order: tuple

def verify_public(bundle,pin,provider):
    """Byte completeness, index signature, known authority and declared graph only."""
    try:
        if type(bundle) is not Bundle or type(bundle.objects) is not dict:raise E('OBJECT_SET')
        v,o=inspect_index(bundle.index,pin);data=dict(bundle.objects)
        ds={d[0]:(d[1],d[2]) for d in v[15]}
        if set(data)!=set(ds):raise E('OBJECT_SET')
        for oid,raw in data.items():
            if type(raw) is not bytes or len(raw)!=ds[oid][1] or object_id(ds[oid][0],raw)!=oid:raise E('OBJECT_HASH')
        used=set()
        def get(oid,kind):
            if oid not in ds or ds[oid][0]!=kind:raise E('OBJECT_REFERENCE')
            used.add(oid);return data[oid]
        replay=get(v[10],'replay')
        try:
            st=restore_public_replay(provider,pin.app,pin.space,pin.head,hashed('auth-local/replay',[replay]),replay,minimum_sequence=pin.sequence)
            st._blocked()
            if st.sequence!=pin.sequence or st.epoch!=pin.epoch:raise E('AUTHORITY_MISMATCH')
            membership=st.membership
        except E:raise
        except Exception:raise E('AUTHORITY_INVALID') from None
        rc=get(v[11],'certificate');ic=get(v[13],'certificate')
        try:
            recipient=member_certificate(provider,pin.app,membership,rc);issuer=member_certificate(provider,pin.app,membership,ic)
            rid=hashed('device-id',[pin.app,recipient[3]]);iid=hashed('device-id',[pin.app,issuer[3]])
            if rid!=pin.recipient_id or objects.certificate_id(rc)!=pin.certificate_id:raise E('NOT_AUTHORIZED')
            if membership.get(rid).role not in (1,2) or membership.get(iid).role!=2:raise E('NOT_AUTHORIZED')
            old=st.membership_at(st.epoch_anchor.id).get(rid)
            if old is None or old.role not in (1,2) or old.certificate_id!=pin.certificate_id:raise E('NOT_AUTHORIZED')
        except E:raise
        except Exception:raise E('NOT_AUTHORIZED') from None
        try:provider.verify(issuer[3],domain('recovery-local/index-sign',[o[0]]),o[1])
        except Exception:raise E('INDEX_SIGNATURE') from None
        g=loads(get(v[12],'grant'));keys(g,range(5));integer(g[0],1,1);fixed(g[1]);fixed(g[3]);ordered_ids(g[2],1024,True)
        if type(g[4]) is not list or len(g[4])>256:raise E('GRANT_INVALID')
        seed_ids=[];seeds={}
        for pair in g[4]:
            if type(pair) is not list or len(pair)!=2:raise E('GRANT_INVALID')
            fixed(pair[0]);fixed(pair[1]);seed_ids.append(pair[0]);raw=get(pair[1],'seed')
            if objects.block_id(raw)!=pair[0]:raise E('GRANT_INVALID')
            seeds[pair[0]]=raw
        if seed_ids!=sorted(set(seed_ids)):raise E('GRANT_INVALID')
        a=st.epoch_anchor.body;package=get(g[1],'package');manifest=get(g[3],'seed-manifest')
        try:
            if objects.package_root(g[2])!=a[8] or objects.package_id(package) not in g[2]:raise ValueError()
            pb=objects._verify_signed(provider,a[11],'key-package-sign','key-package-body',package)
            context={0:pin.app,1:pin.space,2:pin.epoch,3:a[10],4:rid,5:pin.certificate_id,6:a[6]}
            if any(pb[k]!=value for k,value in context.items()):raise ValueError()
            if hashed('auth-local/seed-root',[manifest])!=a[9]:raise ValueError()
            sm=parse_seed_manifest(manifest)
            if any(sm[k]!=value for k,value in ((1,pin.app),(2,pin.space),(3,pin.epoch),(4,a[10]))):raise ValueError()
            if set(seeds)!={e[1] for e in sm[5]}:raise ValueError()
        except Exception:raise E('GRANT_INVALID') from None
        headers={};bindings={}
        for entry in v[14]:
            eid=entry[0];raw=get(entry[1],'envelope');cert_raw=get(entry[2],'certificate')
            h=decode(decode(raw)[0]);objects.change_header(h)
            if objects.envelope_id(raw)!=eid or (h[0],h[1],h[2])!=(pin.app,pin.space,pin.epoch):raise E('ENVELOPE_CONTEXT')
            try:
                node=st.control(h[13]);cert=member_certificate(provider,pin.app,st.membership_at(node.id),cert_raw)
                did=hashed('device-id',[pin.app,cert[3]])
                if node.body[3]!=pin.epoch or did!=h[5] or st.membership_at(node.id).get(did).role!=2:raise ValueError()
                outer=decode(raw);provider.verify(cert[3],domain('envelope-sign',[outer[0],outer[1],outer[2]]),outer[3])
            except Exception:raise E('ENVELOPE_AUTH') from None
            aa=[]
            for bid in entry[4]:
                br=get(bid,'block');bo=objects.parse('sealed-block',br,270336);aa.append(Attachment(objects.block_id(br),bo[0],br))
            try:
                bs=inspect_batch(tuple(aa),h)
                if entry[3] is not None:
                    side=get(entry[3],'attachment');ctx=AttachmentContext(pin.space,pin.epoch,h[3],eid,raw)
                    verify_manifest(provider,cert[3],ctx,bs,side)
                elif bs:raise ValueError()
            except E:raise
            except Exception:raise E('ATTACHMENT_INVALID') from None
            headers[eid]=h;bindings[eid]=bs
        order=closure(v[9],headers)
        if set(order)!=set(headers):raise E('UNREACHABLE_ENVELOPE')
        if used!=set(ds):raise E('OBJECT_UNUSED')
        return PublicSet(v,data,st,rc,{'package':package,'ids':g[2],'manifest':manifest},seeds,bindings,{},order)
    except E:raise
    except Exception:raise E('CLOSURE_INVALID') from None

def verify(bundle,pin,provider,recipient_secret,*,storage_root=None):
    public=verify_public(bundle,pin,provider);st=public.state;g=public.grant
    try:
        st.activate(public.recipient_certificate,recipient_secret,g['package'],g['ids'],g['manifest'],public.seeds)
        st.authorize(public.recipient_certificate,'read')
    except Exception:raise E('RECIPIENT_CRYPTO') from None
    try:
        entries={e[0]:e for e in public.body[14]}
        for eid in public.order:
            e=entries[eid];h=decode(decode(public.data[e[1]])[0])
            candidate=receive_change(st,public.data[e[1]],public.data[e[2]],expected_object=h[3],expected_schema=h[9])
            public.plaintexts[eid]=candidate.payload
    except Exception:raise E('ENVELOPE_CRYPTO') from None
    from .view import RecoveryView
    view=RecoveryView(public,pin,provider,st._active.secret,storage_root=storage_root)
    try:
        for eid,binding in public.bindings.items():
            if binding:view.file_info(eid)
    except Exception:raise E('FILE_INVALID') from None
    return view
