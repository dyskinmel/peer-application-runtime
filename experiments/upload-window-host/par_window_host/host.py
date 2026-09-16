"""Strict host configuration and exclusive offline administration.

No authority signing keys or network administration. Callers provide already
signed grants/commands and an out-of-band trusted minimum pin. Host startup never
initializes an absent schema3 spool or silently migrates legacy data.
"""
from contextlib import contextmanager
from pathlib import Path
import os,stat
from par_keeper.contract import authority_from
from par_keeper_repair import KeeperRepair
from par_keeper_upload.spool import private
from par_upload_window import ReplaySpool,contract as w
from par_recovery.transfer import read_file,put_file
from par_store.fs import safe
from .protocol import E,PROFILE,fixed,integer,keys,dump,load

def check_config(value):
    keys(value,range(13));integer(value[0],1,1)
    if value[1]!=PROFILE:raise E('HOST_CONFIG')
    fixed(value[2]);fixed(value[7])
    try:authority_from(value[3])
    except Exception:raise E('HOST_CONFIG') from None
    for k,maximum in ((4,512*1024*1024),(5,256),(6,65536),(9,16*1024*1024),(10,1024),(11,w.MAX_ARCHIVES),(12,w.MAX_WINDOWS)):
        integer(value[k],1,maximum)
    pin=value[8];keys(pin,range(4));fixed(pin[0]);integer(pin[1],1,value[12]);fixed(pin[2])
    if pin[0]!=value[7]:raise E('WINDOW_PIN')
    if pin[3] is not None:fixed(pin[3])
    return load(dump(value,16384),16384)

def read_config(path):
    private(Path(path));return check_config(load(read_file(path,16384),16384))

def read_secret(fd):
    integer(fd,0,1048575)
    # Avoid waiting for EOF on a terminal/pipe: read exactly the documented 32 bytes.
    secret=bytearray()
    while len(secret)<32:
        b=os.read(fd,32-len(secret))
        if not b:raise E('KEY_INPUT')
        secret.extend(b)
    return secret

@contextmanager
def owned(root,spool_root,cfg,provider,secret,*,allow_unpatched_sqlite=False):
    cfg=check_config(cfg);fixed(secret)
    if provider.sign_public(secret)!=cfg[2]:raise E('KEEPER_IDENTITY')
    root=safe(Path(root));spool_root=safe(Path(spool_root))
    for p in (root,spool_root):private(p,True)
    for p in (root/'keeper.sqlite',spool_root/'LIMITS.cbor',spool_root/'STATE.cbor'):
        if not p.exists():raise E('EXISTING_STATE_REQUIRED')
        private(p)
    disk=w.load(read_file(spool_root/'LIMITS.cbor',4096))
    expected={0:3,1:w.PROFILE,2:cfg[2],3:cfg[7],4:cfg[9],5:cfg[10],6:cfg[11],7:cfg[12]}
    if disk!=expected:raise E('WINDOW_SETTINGS_OR_LEGACY')
    with KeeperRepair(root,provider,secret,authority_from(cfg[3]),quota_bytes=cfg[4],max_leases=cfg[5],max_operations=cfg[6],allow_unpatched_sqlite=allow_unpatched_sqlite) as k:
        with ReplaySpool(k,spool_root,cfg[7],max_bytes=cfg[9],max_records=cfg[10],max_archive_bytes=cfg[11],max_windows=cfg[12],expected_pin=cfg[8]) as gateway:
            if gateway.window is None:raise E('WINDOW_REQUIRED')
            yield k,gateway

def administer(gateway,action,*,command=None,archive=None):
    """Trusted local boundary only. Do not call through the data service dispatcher."""
    if action=='inspect':
        if command is not None or archive is not None:raise E('ADMIN_INPUT')
        return dump(gateway.pin(),4096)
    if action=='export':
        if command is not None or archive is not None:raise E('ADMIN_INPUT')
        return gateway.export_archive()
    if action=='close':
        if command is None or archive is None:raise E('ADMIN_INPUT')
        return dump(gateway.close_window(command,archive),4096)
    if action=='compact':
        if command is not None or archive is not None:raise E('ADMIN_INPUT')
        return gateway.compact()
    if action=='open':
        if command is None or archive is not None:raise E('ADMIN_INPUT')
        return dump(gateway.open_window(command),4096)
    if action in ('retire','rebind'):
        if command is None or archive is not None:raise E('ADMIN_INPUT')
        b=w.check_command(gateway.provider,gateway.window,command)
        if b[3]!=action:raise E('METHOD_DENIED')
        result=gateway.execute(command)
        return dump([[k,v] for k,v in sorted(result.items())],w.MAX_CONTROL)
    raise E('METHOD_DENIED')
