"""Private cooperative-writer staging. Atomic artifacts, never plaintext metadata.

Not an OS sandbox or anti-rollback service. Store's lifetime writer lock owns this
namespace. Only unacknowledged *.part files may be removed; no committed Blob GC.
"""
from __future__ import annotations
import os,stat,tempfile,re
from pathlib import Path
from par_store.fs import safe,sync_dir
from .errors import FileError as E

MAX_ARTIFACT=270336

def read_bounded(path: Path,limit=MAX_ARTIFACT) -> bytes:
    path=safe(path)
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:raise E('FILE_ARTIFACT_MISSING') from None
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=limit:raise E('FILE_ARTIFACT_INVALID')
        with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(limit+1)
        if not 0<len(raw)<=limit or len(raw)!=st.st_size:raise E('FILE_ARTIFACT_INVALID')
        return raw
    finally:
        if fd is not None:os.close(fd)

def make_dir(path: Path) -> None:
    path=safe(path)
    if not path.exists():path.mkdir(mode=0o700);sync_dir(path.parent)
    if not path.is_dir():raise E('UNSAFE_PATH')

def durable_existing(path: Path) -> None:
    fd=os.open(safe(path),os.O_RDONLY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    sync_dir(path.parent)

def publish(path: Path,raw:bytes,notify,prefix:str) -> None:
    """Publish an immutable ciphertext artifact. Retry may see an unacknowledged file."""
    path=safe(path)
    if path.exists():
        if read_bounded(path)!=raw:raise E('FILE_ARTIFACT_INVALID')
        durable_existing(path);return
    fd,name=tempfile.mkstemp(prefix='.write-',suffix='.part',dir=path.parent);tmp=Path(name)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();notify(prefix+'.written');os.fsync(f.fileno());notify(prefix+'.synced')
        # link is same-directory, atomic, no-overwrite. No user-controlled filenames.
        os.link(tmp,path,follow_symlinks=False);notify(prefix+'.published')
        tmp.unlink();sync_dir(path.parent);notify(prefix+'.durable')
    finally:
        if tmp.exists():tmp.unlink()

def clean_unacknowledged(root: Path, expected: set[str]) -> None:
    paths=list(root.iterdir())
    if len(paths)>128:raise E('FILE_STAGE_BUDGET')
    for p in paths:
        safe(p)
        if not p.is_file():raise E('FILE_ARTIFACT_INVALID')
        if p.name in expected:continue
        if re.fullmatch(r'\.write-[a-zA-Z0-9_-]+\.part',p.name):p.unlink()
        else:raise E('FILE_ARTIFACT_INVALID')
    sync_dir(root)
