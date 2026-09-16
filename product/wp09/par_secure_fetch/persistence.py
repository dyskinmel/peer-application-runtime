"""Private create-only metadata. Caller retains hashes outside this directory.

No secrets/payloads; identifiers are still privacy-sensitive. No rollback oracle,
no atomic transaction with Inbox, no replacement and no orphan deletion.
"""
from pathlib import Path
import hashlib,hmac,os,re
from product.wp04.inbox import private_dir,read_file
from par_store.fs import safe,sync_dir

MAX_METADATA = 65536
class FetchError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

def require(ok,code='INVALID_PLAN'):
    if not ok:raise FetchError(code)

def save_new(path,raw):
    require(type(raw)is bytes and 0<len(raw)<=MAX_METADATA,'METADATA_LIMIT')
    try:
        path=safe(Path(path));private_dir(path.parent)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb')as f:
            os.fchmod(f.fileno(),0o600);f.write(raw);f.flush();os.fsync(f.fileno())
        sync_dir(path.parent)
    except Exception:raise FetchError('METADATA_SAVE_FAILED')from None
    return hashlib.sha256(raw).hexdigest()

def load_pinned(path,expected_sha256):
    require(type(expected_sha256)is str and re.fullmatch('[0-9a-f]{64}',expected_sha256)is not None,'METADATA_PIN')
    try:
        path=safe(Path(path));private_dir(path.parent);raw=read_file(path,MAX_METADATA)
    except Exception:raise FetchError('METADATA_READ_FAILED')from None
    require(hmac.compare_digest(hashlib.sha256(raw).hexdigest(),expected_sha256),'METADATA_PIN')
    return raw
