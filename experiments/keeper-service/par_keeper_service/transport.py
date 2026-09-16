"""Linux private pathname sockets. No TCP, abstract addresses or silent fallback."""
from __future__ import annotations
from pathlib import Path
import errno,fcntl,os,socket,stat,struct,sys,time
from par_store.fs import safe
from .errors import ServiceError as E

def frame(raw,limit):
    if type(raw) is not bytes or not 1<=len(raw)<=limit:raise E('FRAME_LIMIT')
    return struct.pack('>I',len(raw))+raw

def remaining(deadline):
    left=deadline-time.monotonic()
    if left<=0:raise E('DEADLINE')
    return left

def receive(sock,limit,deadline):
    """Read exactly one bounded frame. Progress never extends the absolute deadline."""
    data=bytearray();want=4
    try:
        while len(data)<want:
            sock.settimeout(remaining(deadline))
            b=sock.recv(want-len(data))
            if not b:raise E('DISCONNECTED')
            data.extend(b)
            if want==4 and len(data)==4:
                n=struct.unpack('>I',data)[0]
                if not 1<=n<=limit:raise E('FRAME_LIMIT')
                want=4+n
        return bytes(data[4:])
    except socket.timeout:raise E('DEADLINE') from None
    except OSError:raise E('DISCONNECTED') from None

def send(sock,raw,limit,deadline):
    sock.settimeout(remaining(deadline))
    try:sock.sendall(frame(raw,limit))
    except socket.timeout:raise E('DEADLINE') from None
    except OSError:raise E('DISCONNECTED') from None

def peer_uid(sock):
    if not sys.platform.startswith('linux') or not hasattr(socket,'SO_PEERCRED'):raise E('UNSUPPORTED_PLATFORM')
    try:pid,uid,gid=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
    except OSError:raise E('PEER_IDENTITY') from None
    if uid!=os.getuid():raise E('PEER_IDENTITY')
    return uid

def private_path(path):
    if not sys.platform.startswith('linux'):raise E('UNSUPPORTED_PLATFORM')
    if not isinstance(path,(str,os.PathLike)):raise E('SOCKET_PATH')
    try:
        path=Path(path)
        if not path.is_absolute() or '..' in path.parts or '\0' in str(path) or len(os.fsencode(path))>103:raise E('SOCKET_PATH')
        safe(path)
        parent=path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)!=0o700:raise E('SOCKET_PERMISSIONS')
        return path
    except E:raise
    except Exception:raise E('SOCKET_PATH') from None

def socket_identity(path):
    path=private_path(path)
    try:s=path.lstat()
    except OSError:raise E('SOCKET_MISSING') from None
    if not stat.S_ISSOCK(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise E('SOCKET_PERMISSIONS')
    return s.st_dev,s.st_ino

class EndpointLock:
    def __init__(self,path):
        self.fd=None;self.path=private_path(path);lock=self.path.with_name(self.path.name+'.lock')
        try:
            fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);self.fd=fd;s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise E('SOCKET_PERMISSIONS')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise E('ENDPOINT_BUSY') from None
        except BaseException:
            self.close();raise
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None

class Endpoint:
    def __init__(self,path,backlog):
        self.lock=None;self.socket=None;self.identity=None;self.path=private_path(path)
        self.parent_identity=(self.path.parent.stat().st_dev,self.path.parent.stat().st_ino)
        try:
            self.lock=EndpointLock(self.path)
            if self.path.exists():raise E('SOCKET_EXISTS')
            self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            self.socket.bind(str(self.path));os.chmod(self.path,0o600)
            self.identity=socket_identity(self.path)
            self.socket.listen(backlog);self.socket.setblocking(False)
        except BaseException:self.close();raise
    def close(self):
        if self.socket is not None:self.socket.close();self.socket=None
        try:
            if self.identity is not None and self.path.exists():
                s=self.path.parent.stat()
                if (s.st_dev,s.st_ino)==self.parent_identity and socket_identity(self.path)==self.identity:self.path.unlink()
        except (E,OSError):pass # Do not remove another process's replacement.
        finally:
            if self.lock is not None:self.lock.close();self.lock=None

def recover_stale(path,expected_identity):
    """Explicit trusted-operator action. Refuse live/locked or substituted endpoints."""
    path=private_path(path)
    if type(expected_identity) not in (tuple,list) or len(expected_identity)!=2 or any(type(x) is not int for x in expected_identity):raise E('SOCKET_IDENTITY')
    lock=EndpointLock(path)
    try:
        if socket_identity(path)!=tuple(expected_identity):raise E('SOCKET_IDENTITY')
        probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);probe.settimeout(.2)
        try:
            probe.connect(str(path))
        except OSError as ex:
            if ex.errno!=errno.ECONNREFUSED:raise E('ENDPOINT_UNCERTAIN') from None
        else:raise E('ENDPOINT_ACTIVE')
        finally:probe.close()
        if socket_identity(path)!=tuple(expected_identity):raise E('SOCKET_IDENTITY')
        path.unlink()
    finally:lock.close()
