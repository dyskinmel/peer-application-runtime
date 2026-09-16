"""POSIX publication port for a cooperating single writer in a private local directory.

Known symlinks are rejected. This is not protection against an adversarial same-UID
process racing directory replacements; an OS sandbox is a separate requirement.
"""
from __future__ import annotations
import errno, os, re, stat, tempfile
from pathlib import Path
from .errors import StoreError
from .model import fixed,sha,bounded,BLOCK_MAX

def safe(path: Path) -> Path:
    path=Path(os.path.abspath(path))
    for p in (path,*path.parents):
        if p.is_symlink():raise StoreError('UNSAFE_PATH')
    return path

def regular(path: Path):
    safe(path)
    if not path.is_file():raise StoreError('UNSAFE_PATH')

def sync_dir(path: Path):
    if os.name!='posix':raise StoreError('UNSUPPORTED_HOST')
    fd=os.open(safe(path),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

class WriterLock:
    def __init__(self,root:Path):
        if os.name!='posix':raise StoreError('UNSUPPORTED_HOST')
        import fcntl
        self.fd=None
        path=safe(root/'.store.lock')
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise StoreError('UNSAFE_PATH')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd);raise StoreError('WRITER_BUSY') from None
        except BaseException:
            os.close(fd);raise
        self.fd=fd
    def close(self):
        if self.fd is not None:
            import fcntl
            fcntl.flock(self.fd,fcntl.LOCK_UN);os.close(self.fd);self.fd=None

class BlockPort:
    def __init__(self,root:Path,observe):
        self.root=safe(root);self.observe=observe
        self.sync_file=os.fsync
        for name in ('blocks','staging'):
            p=safe(root/name);p.mkdir(mode=0o700,exist_ok=True)
            if not p.is_dir():raise StoreError('UNSAFE_PATH')
    def path(self,block_id:bytes)->Path:
        fixed(block_id,32);return safe(self.root/'blocks'/block_id.hex())
    def read(self,block_id:bytes)->bytes:
        p=self.path(block_id)
        if not p.exists():raise StoreError('BLOCK_MISSING')
        regular(p)
        if not 1<=p.stat().st_size<=BLOCK_MAX:raise StoreError('BLOCK_CORRUPT')
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as f:data=f.read(BLOCK_MAX+1)
        if sha(data)!=block_id:raise StoreError('BLOCK_CORRUPT')
        return data
    def publish(self,data:bytes)->bytes:
        bounded(data,BLOCK_MAX);bid=sha(data);dest=self.path(bid)
        if dest.exists():
            if self.read(bid)!=data:raise StoreError('BLOCK_CORRUPT')
            # An earlier process could have died after rename but before directory sync.
            fd=os.open(dest,os.O_RDONLY|os.O_NOFOLLOW)
            try:self.sync_file(fd)
            finally:os.close(fd)
            self.observe('block.after_fsync');sync_dir(dest.parent);self.observe('block.after_dirsync')
            return bid
        fd,name=tempfile.mkstemp(prefix='block-',suffix='.part',dir=safe(self.root/'staging'))
        p=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data);f.flush();self.observe('block.after_write')
                self.sync_file(f.fileno());self.observe('block.after_fsync')
            # The lifetime writer lock serializes all cooperating publish / GC operations.
            safe(dest)
            if dest.exists():raise StoreError('BLOCK_CORRUPT')
            os.rename(p,dest);self.observe('block.after_rename')
            sync_dir(dest.parent);sync_dir(p.parent);self.observe('block.after_dirsync')
            return bid
        finally:
            # A SIGKILL leaves a .part; explicit orphan GC, not normal open, can remove it.
            if p.exists():p.unlink()
