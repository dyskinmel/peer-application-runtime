"""Bounded whole-object local transport. No sockets, credentials or ready-flag trust.

Private POSIX directories and cooperative single writers only. Ciphertext .part
files are crash debris; a received object is acknowledged after directory fsync.
A complete inventory is NOT proof that the recipient can recover its contents.
"""
from __future__ import annotations
import os,stat,tempfile,re,shutil,threading
from pathlib import Path
from par_store.fs import safe,sync_dir,WriterLock
from .contract import *
from .verify import verify
from .errors import RecoveryError as E

PART=re.compile(r'\.rc-part-[a-zA-Z0-9_-]+')

def checked_path(path):
    try:return safe(Path(path))
    except Exception:raise E('UNSAFE_PATH') from None

def read_file(path,limit=MAX_OBJECT):
    path=checked_path(path);fd=None
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=limit:raise E('OBJECT_HASH')
        # Allocate for the observed file, not the largest permitted object. Read
        # one extra byte to detect growth; metadata only detects local races and
        # does not replace the caller's content-hash/signature verification.
        def identity(s):
            return (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        with os.fdopen(fd,'rb') as f:
            fd=None;raw=f.read(st.st_size+1)
            after=os.fstat(f.fileno())
            named=os.stat(path,follow_symlinks=False)
            if identity(st)!=identity(after) or identity(after)!=identity(named):
                raise E('OBJECT_HASH')
        if len(raw)!=st.st_size or len(raw)>limit:raise E('OBJECT_HASH')
        return raw
    except FileNotFoundError:raise E('OBJECT_MISSING') from None
    except OSError:raise E('TRANSFER_IO') from None
    finally:
        if fd is not None:os.close(fd)

def mkdir(path):
    path=checked_path(path)
    if not path.exists():path.mkdir(mode=0o700);sync_dir(path.parent)
    if not path.is_dir():raise E('UNSAFE_PATH')

def emit(observer,event):
    if observer:
        try:observer(event)
        except Exception:raise E('TRANSFER_INTERRUPTED') from None

def put_file(path,raw,observer=None,prefix='object'):
    path=checked_path(path)
    if path.exists():
        if read_file(path,max(MAX_OBJECT,MAX_INDEX))!=raw:raise E('OBJECT_HASH')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        sync_dir(path.parent);return 'DUPLICATE'
    tmp=None;published=False
    try:
        fd,name=tempfile.mkstemp(prefix='.rc-part-',dir=path.parent);tmp=Path(name)
        with os.fdopen(fd,'wb') as out:
            out.write(raw);out.flush();emit(observer,prefix+'.written')
            os.fsync(out.fileno());emit(observer,prefix+'.synced')
        os.link(tmp,path,follow_symlinks=False);published=True;emit(observer,prefix+'.published')
        tmp.unlink();sync_dir(path.parent);emit(observer,prefix+'.durable')
        emit(observer,prefix+'.ack');return 'ACCEPTED'
    except BaseException as ex:
        if published:raise E('TRANSFER_OUTCOME_UNKNOWN') from None
        if isinstance(ex,OSError):raise E('TRANSFER_IO') from None
        raise
    finally:
        if tmp is not None and tmp.exists():
            try:tmp.unlink()
            except OSError:pass  # Keep the original outcome; next locked resume cleans owned debris.

def _self_pin(index):
    # Structural upload bound only. Never returned as an authenticated recipient pin.
    v=loads(loads(index)[0])
    return Pin(v[2],v[3],v[4],v[5],v[6],v[7],v[8],tuple(v[9]),index_id(index))

def _directory_inventory(root,descriptors,*,clean=False):
    for p in root.iterdir():
        checked_path(p)
        if p.name not in ('index.cbor','objects','.store.lock'):
            if clean and PART.fullmatch(p.name) and p.is_file():p.unlink()
            else:raise E('UNEXPECTED_FILE')
    blockdir=checked_path(root/'objects');paths=list(blockdir.iterdir())
    if len(paths)>MAX_OBJECTS+64:raise E('CLOSURE_LIMIT')
    have={}
    for p in paths:
        checked_path(p)
        if clean and PART.fullmatch(p.name) and p.is_file():p.unlink();continue
        if not re.fullmatch(r'[0-9a-f]{64}',p.name):raise E('UNEXPECTED_FILE')
        oid=bytes.fromhex(p.name)
        if oid not in descriptors:raise E('UNEXPECTED_FILE')
        raw=read_file(p);kind,n=descriptors[oid]
        if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
        have[oid]=raw
    if clean:sync_dir(blockdir);sync_dir(root)
    return have

class Inbox:
    """One index and external pin per root. Resume derives progress from exact bytes."""
    def __init__(self,root,index,pin,*,observer=None):
        self._lock=None;self._closed=True;self._busy=False;self._thread=threading.get_ident()
        self.body,_=inspect_index(index,pin);self.index=index;self.pin=pin
        self.ds={d[0]:(d[1],d[2]) for d in self.body[15]};self.observer=observer
        self.root=checked_path(root)
        try:
            mkdir(self.root)
            try:self._lock=WriterLock(self.root)
            except Exception as ex:raise E(getattr(ex,'code','UNSAFE_PATH')) from None
            mkdir(self.root/'objects')
            existing=self.root/'index.cbor'
            if existing.exists() and read_file(existing,MAX_INDEX)!=index:raise E('INDEX_CHANGED')
            put_file(existing,index)
            _directory_inventory(self.root,self.ds,clean=True)
            self._closed=False
        except BaseException as ex:
            self.close()
            if isinstance(ex,OSError):raise E('TRANSFER_IO') from None
            raise
    def close(self):
        if self._lock is not None:self._lock.close();self._lock=None
        self._closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def _check(self):
        if self._closed:raise E('CLOSED')
        if threading.get_ident()!=self._thread:raise E('WRONG_THREAD')
        if self._busy:raise E('REENTRANT_OPERATION')
        if read_file(self.root/'index.cbor',MAX_INDEX)!=self.index:raise E('INDEX_CHANGED')
    def missing(self):
        self._check();have=_directory_inventory(self.root,self.ds)
        return tuple(sorted(set(self.ds)-set(have)))
    def status(self):
        missing=self.missing()
        return {'state':'MISSING_OBJECTS' if missing else 'BYTES_COMPLETE','missing':[i.hex() for i in missing],
                'recipient_validated':False,'applied':False,'product_qualified':False}
    def put(self,oid,raw):
        self._check();fixed(oid)
        if oid not in self.ds:raise E('OBJECT_REFERENCE')
        kind,n=self.ds[oid]
        if type(raw) is not bytes or len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
        self._busy=True
        try:return put_file(self.root/'objects'/oid.hex(),raw,self.observer)
        finally:self._busy=False
    def bundle(self):
        self._check();data=_directory_inventory(self.root,self.ds)
        if set(data)!=set(self.ds):raise E('OBJECT_SET')
        return Bundle(self.index,data)
    def pull(self,provider,*,limit=32):
        if type(limit) is not int or not 1<=limit<=MAX_OBJECTS:raise E('TRANSFER_LIMIT')
        chosen=self.missing()[:limit];received=0;absent=[]
        for oid in chosen:
            self._busy=True
            try:raw=provider.fetch(oid)
            finally:self._busy=False
            if raw is None:absent.append(oid.hex());continue
            self.put(oid,raw);received+=1
        return {'received':received,'provider_missing':absent,'remaining':len(self.missing())}
    def finalize(self,destination,provider,recipient_secret):
        self._check();destination=checked_path(destination)
        if destination==self.root or destination.is_relative_to(self.root):raise E('UNSAFE_PATH')
        if destination.exists():raise E('DESTINATION_EXISTS')
        if not destination.parent.is_dir():raise E('UNSAFE_PATH')
        bundle=self.bundle();self._busy=True;stage=None;published=False
        try:
            verify(bundle,self.pin,provider,recipient_secret,storage_root=self.root)
            emit(self.observer,'finalize.verified')
            stage=Path(tempfile.mkdtemp(prefix='.rc-output-',dir=destination.parent))
            publish_bundle(bundle,stage)
            view=open_recovery(stage,self.pin,provider,recipient_secret)
            emit(self.observer,'finalize.stage_verified')
            checked_path(destination)
            if destination.exists():raise E('DESTINATION_EXISTS')
            os.rename(stage,destination);published=True
            emit(self.observer,'finalize.published');sync_dir(destination.parent)
            emit(self.observer,'finalize.durable');emit(self.observer,'finalize.ack')
            # Rebind file-export exclusion to the actual destination, not the old stage.
            view._storage.root=destination;return view
        except BaseException as ex:
            if published:raise E('RECOVERY_OUTCOME_UNKNOWN') from None
            if isinstance(ex,OSError):raise E('TRANSFER_IO') from None
            raise
        finally:
            self._busy=False
            if stage is not None and stage.exists():
                try:shutil.rmtree(stage)
                except OSError:pass  # Private ciphertext debris, not a reason to overwrite the original failure.

class DirectoryProvider:
    """Local opaque byte adapter; not an authenticated network peer or Keeper lease."""
    def __init__(self,root,index,pin):
        v,_=inspect_index(index,pin);self.ds={d[0]:(d[1],d[2]) for d in v[15]}
        self.root=checked_path(root);self.index=index
        if read_file(self.root/'index.cbor',MAX_INDEX)!=index:raise E('INDEX_CHANGED')
    def fetch(self,oid):
        fixed(oid)
        if oid not in self.ds:raise E('OBJECT_REFERENCE')
        if read_file(self.root/'index.cbor',MAX_INDEX)!=self.index:raise E('INDEX_CHANGED')
        try:raw=read_file(self.root/'objects'/oid.hex())
        except E as ex:
            if ex.code=='OBJECT_MISSING':return None
            raise
        kind,n=self.ds[oid]
        if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
        return raw

def publish_bundle(bundle,destination):
    """Publish opaque bytes only. This call does NOT validate recipient recovery."""
    try:pin=_self_pin(bundle.index)
    except Exception:raise E('INDEX_SCHEMA') from None
    v,_=inspect_index(bundle.index,pin)
    if type(bundle.objects) is not dict or set(bundle.objects)!={d[0] for d in v[15]}:raise E('OBJECT_SET')
    with Inbox(destination,bundle.index,pin) as rx:
        for oid,raw in bundle.objects.items():rx.put(oid,raw)
        rx.bundle()

def open_recovery(root,pin,provider,recipient_secret):
    root=checked_path(root);index=read_file(root/'index.cbor',MAX_INDEX)
    v,_=inspect_index(index,pin);ds={d[0]:(d[1],d[2]) for d in v[15]}
    data=_directory_inventory(root,ds)
    return verify(Bundle(index,data),pin,provider,recipient_secret,storage_root=root)
