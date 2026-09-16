"""Verify every ordered chunk, aggregate size and digest before publishing plaintext.

The output path is explicit; stored file metadata is never interpreted as a path.
Crash leftovers may contain plaintext with mode 0600. No secure-erasure promise.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib,os,tempfile
from par_blob_store import Attachment
from par_crypto import objects
from par_wire.codec import decode
from par_store.fs import safe,sync_dir
from .errors import FileError as E
from . import manifest as M

@dataclass(frozen=True)
class FileInfo:
    file_id: bytes
    name: str
    media_type: str
    size: int
    sha256: bytes
    chunks: int
    complete: bool=True

def _prepare(store,eid,secret):
    store._enter();bindings=store.attachments(eid)
    if not bindings:raise E('FILE_MANIFEST_MISSING')
    first=bindings[0]
    a=Attachment(first.typed_id,first.header_bytes,store._storage.read_block(first.locator))
    v=M.open_manifest(store._provider,secret,a,app=first.app,space=first.space,epoch=first.epoch)
    M.check_bindings(v,bindings[1:]);return v,bindings[1:]

def _consume(store,secret,v,bindings,write,notify):
    sha=hashlib.sha256();total=0
    for i,b in enumerate(bindings):
        raw=store._storage.read_block(b.locator)
        if objects.block_id(raw)!=b.typed_id:raise E('FILE_CHUNK_SET')
        data=objects.open_block(store._provider,secret,decode(b.header_bytes),raw)
        total+=len(data);sha.update(data);write(data);notify(f'file.export.chunk.{i}')
    if total!=v[7] or sha.digest()!=v[9]:raise E('FILE_HASH_MISMATCH')
    return FileInfo(v[5],v[10],v[11],total,sha.digest(),len(bindings))

def inspect_file(store,eid,secret):
    v,bindings=_prepare(store,eid,secret)
    return _consume(store,secret,v,bindings,lambda data:None,lambda event:None)

def export_file(store,eid,secret,destination,*,observer=None):
    destination=safe(Path(destination));root=store._storage.root
    if destination.is_relative_to(root):raise E('UNSAFE_PATH')
    if destination.exists():raise E('DESTINATION_EXISTS')
    if not destination.parent.is_dir():raise E('UNSAFE_PATH')
    v,bindings=_prepare(store,eid,secret)
    def notify(event):
        if observer:
            try:observer(event)
            except Exception:raise E('FILE_EXPORT_INTERRUPTED') from None
    published=False;tmp=None
    try:
        fd,name=tempfile.mkstemp(prefix='.par-export-',suffix='.part',dir=destination.parent);tmp=Path(name)
        with os.fdopen(fd,'wb') as out:
            info=_consume(store,secret,v,bindings,out.write,notify)
            out.flush();os.fsync(out.fileno());notify('file.export.verified')
        safe(destination)
        try:os.link(tmp,destination,follow_symlinks=False)
        except FileExistsError:raise E('DESTINATION_EXISTS') from None
        published=True;notify('file.export.published');sync_dir(destination.parent)
        tmp.unlink();sync_dir(destination.parent);notify('file.export.ack');return info
    except BaseException as exc:
        if published:raise E('FILE_EXPORT_OUTCOME_UNKNOWN') from None
        if isinstance(exc,OSError):raise E('FILE_EXPORT_IO_FAILED') from None
        raise
    finally:
        if tmp is not None and tmp.exists():tmp.unlink()
