"""Owner-supplied journal checkpoint storage.

LocalPinStore is a single-writer POSIX adapter, NOT a hardware trust anchor. The
owner must protect this directory independently from the journal. Rolling back
both stores, a malicious same-UID writer, and stale unobserved tails remain out
of scope. Enrolment is explicit: open never creates a missing pin.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import fcntl,json,os,stat,threading
from pathlib import Path
from product.wp04.contracts import canonical
from product.wp04.inbox import private_dir,read_file
from product.wp09.par_secure_fetch.persistence import require,FetchError,save_new
from par_store.fs import safe,sync_dir
from .model import JournalPin,check_binding

PROFILE='par-intent-pin-posix-0051'
MAX_PIN_BYTES=4096

class PinStore(ABC):
    """Trusted owner port. advance is durable compare-and-swap, not a claim flag.

    Implementations bind one immutable document/store/device binding. load must
    fail on missing/corrupt/unavailable data; never return an invented initial
    value. Success from advance means the checkpoint is durably stored. Failure
    may mean stored-but-response-lost; callers must stop and explicitly reopen.
    """
    binding:bytes

    @abstractmethod
    def load(self)->JournalPin: ...

    @abstractmethod
    def advance(self,expected:JournalPin,value:JournalPin)->None: ...

class LocalPinStore(PinStore):
    """One separate 0700 directory, 0600 files, nonblocking exclusive lease.

    Atomic replacement + file and directory fsync; incomplete pending writes are
    preserved as diagnostics and refuse open. Metadata is NOT encrypted. The
    class implements local durability, not protection against filesystem rollback.
    """
    @classmethod
    def create(cls,root,binding,pin):
        binding=check_binding(binding);require(type(pin)is JournalPin,'JOURNAL_PIN')
        root=safe(Path(root));private_dir(root.parent)
        require(not root.exists(),'PIN_STORE_EXISTS')
        root.mkdir(mode=0o700)
        save_new(root/'pin.json',cls._encode(binding,pin))
        fd=os.open(root/'lease',os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:os.fchmod(fd,0o600);os.fsync(fd)
        finally:os.close(fd)
        sync_dir(root);sync_dir(root.parent)
        return cls.open(root,binding)

    @classmethod
    def open(cls,root,binding):
        self=cls.__new__(cls);self.binding=check_binding(binding)
        self.root=safe(Path(root));self._fd=None;self._known=None
        self._closed=False;self._poisoned=False;self._owner=(os.getpid(),threading.get_ident())
        try:
            private_dir(self.root);s=self.root.stat();self._identity=(s.st_dev,s.st_ino)
            self._layout()
            fd=os.open(self.root/'lease',os.O_RDWR|os.O_NOFOLLOW);self._fd=fd
            s=os.fstat(fd)
            require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and s.st_uid==os.getuid()and stat.S_IMODE(s.st_mode)==0o600,'UNSAFE_PATH')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise FetchError('PIN_STORE_LOCKED')from None
            self._lease_identity=(s.st_dev,s.st_ino)
            self._known=self._read()
            # Reopening is explicit recovery: re-sync observed valid pin bytes.
            fd=os.open(self.root/'pin.json',os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
            sync_dir(self.root)
            return self
        except BaseException:
            if self._fd is not None:os.close(self._fd);self._fd=None
            self._closed=True;raise

    @staticmethod
    def _encode(binding,pin):
        return canonical({'profile':PROFILE,'binding':binding.hex(),
            'pin':{'metadataDigest':pin.metadata_digest,'sequence':pin.sequence,'eventDigest':pin.event_digest}})

    def _layout(self):
        require({p.name for p in self.root.iterdir()}=={'pin.json','lease'},'PIN_STORE_UNCERTAIN')

    def _guard(self):
        require(self._owner==(os.getpid(),threading.get_ident()),'WRONG_OWNER')
        require(not self._closed,'PIN_STORE_CLOSED');require(not self._poisoned,'PIN_STORE_POISONED')
        private_dir(self.root);s=self.root.stat()
        require((s.st_dev,s.st_ino)==self._identity,'PIN_STORE_REPLACED')
        self._layout()
        s=(self.root/'lease').lstat()
        require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and (s.st_dev,s.st_ino)==self._lease_identity,'PIN_STORE_REPLACED')
        require(s.st_uid==os.getuid()and stat.S_IMODE(s.st_mode)==0o600,'UNSAFE_PATH')

    def _read(self):
        raw=read_file(self.root/'pin.json',MAX_PIN_BYTES)
        try:
            v=json.loads(raw)
            require(type(v)is dict and set(v)=={'profile','binding','pin'}and v['profile']==PROFILE,'PIN_STORE_CORRUPT')
            require(v['binding']==self.binding.hex(),'PIN_STORE_BINDING')
            p=v['pin'];require(type(p)is dict and set(p)=={'metadataDigest','sequence','eventDigest'},'PIN_STORE_CORRUPT')
            pin=JournalPin(p['metadataDigest'],p['sequence'],p['eventDigest'])
            require(raw==self._encode(self.binding,pin),'PIN_STORE_CORRUPT')
            return pin
        except FetchError:raise
        except Exception:raise FetchError('PIN_STORE_CORRUPT')from None

    def load(self):
        self._guard();pin=self._read()
        require(pin==self._known,'PIN_STORE_CONFLICT')
        return pin

    def advance(self,expected,value):
        require(type(expected)is JournalPin and type(value)is JournalPin,'JOURNAL_PIN')
        current=self.load();require(current==expected,'PIN_STORE_CONFLICT')
        require(value.metadata_digest==current.metadata_digest,'PIN_STORE_BINDING')
        require(value.sequence>=current.sequence,'PIN_STORE_REGRESSION')
        if value.sequence==current.sequence:
            require(value==current,'PIN_STORE_CONFLICT');return
        # A PinStore does not authenticate a chain by itself: IntentJournal has
        # verified the prefix. This port only durably fences the owner's decision.
        raw=self._encode(self.binding,value)
        try:
            save_new(self.root/'pending.json',raw)
            os.replace(self.root/'pending.json',self.root/'pin.json')
            sync_dir(self.root)
            self._known=value
        except BaseException as exc:
            self._poisoned=True
            if not isinstance(exc,Exception):raise
            raise FetchError('PIN_STORE_UNCERTAIN')from None

    def close(self):
        if self._closed:return
        require(self._owner==(os.getpid(),threading.get_ident()),'WRONG_OWNER')
        self._closed=True
        if self._fd is not None:os.close(self._fd);self._fd=None
