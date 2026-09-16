"""Private-directory POSIX replacement under the Keeper lifetime writer lock.

Identity checks are race detection for cooperating processes, not a sandbox against
an adversary who controls the same OS account. Only exact job-owned stage files
are cleaned; unknown names, links and directories stop the operation.
"""
import os,stat
from pathlib import Path
from par_store.fs import safe,sync_dir
from par_recovery.contract import object_id
from par_recovery.transfer import mkdir
from par_keeper.errors import KeeperError as E

def regular(path):
    path=safe(path)
    try:s=path.lstat()
    except FileNotFoundError:return None
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise E('REPAIR_UNSAFE_FILE')
    return s

def probe(path,kind,size,oid):
    s=regular(path)
    if s is None:return ('missing',None)
    ident=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if s.st_size!=size:return ('corrupt',ident)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        opened=os.fstat(fd)
        if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)!=ident:raise E('REPAIR_FILE_CHANGED')
        raw=b''
        while len(raw)<=size:
            part=os.read(fd,min(65536,size+1-len(raw)))
            if not part:break
            raw+=part
        last=os.fstat(fd)
        if (last.st_dev,last.st_ino,last.st_size,last.st_mtime_ns,last.st_ctime_ns)!=ident:raise E('REPAIR_FILE_CHANGED')
    finally:os.close(fd)
    return ('valid' if len(raw)==size and object_id(kind,raw)==oid else 'corrupt',ident)

def job_path(root,jid):return safe(root/'repair-staging'/jid.hex())

def check_stage(root,jid,oids):
    d=job_path(root,jid)
    if not d.exists():return
    if not d.is_dir():raise E('REPAIR_UNSAFE_FILE')
    names={oid.hex()+'.part' for oid in oids}
    with os.scandir(d) as entries:
        for e in entries:
            if e.name not in names:raise E('REPAIR_UNKNOWN_FILE')
            regular(d/e.name)

def clean_stage(root,jid,oids,emit):
    d=job_path(root,jid);check_stage(root,jid,oids)
    if d.exists():
        for oid in oids:
            p=safe(d/(oid.hex()+'.part'))
            if regular(p) is not None:
                os.unlink(p);emit('repair_cleanup.unlinked');sync_dir(d)
        os.rmdir(d);emit('repair_cleanup.removed')
    sync_dir(root/'repair-staging');emit('repair_cleanup.durable')

def replace_object(root,jid,lid,oid,kind,size,raw,emit,recheck):
    stage=job_path(root,jid);mkdir(stage)
    outdir=safe(root/'objects'/lid.hex());mkdir(outdir)
    target=safe(outdir/oid.hex());temp=safe(stage/(oid.hex()+'.part'))
    before=probe(target,kind,size,oid)
    if before[0]=='valid':
        fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        sync_dir(outdir);recheck();return
    # An existing stage belongs to this durable job and is revalidated, never
    # trusted as progress. Partial stage bytes may be discarded, not target bytes.
    if regular(temp) is not None:
        if probe(temp,kind,size,oid)[0]!='valid':os.unlink(temp);sync_dir(stage)
    if not temp.exists():
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();emit('repair_file.written');os.fsync(f.fileno());emit('repair_file.synced')
        except BaseException:raise
    else:
        fd=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    sync_dir(stage);emit('repair_file.staged')
    if probe(temp,kind,size,oid)[0]!='valid':raise E('OBJECT_HASH')
    emit('repair_file.before_replace');recheck()
    if probe(temp,kind,size,oid)[0]!='valid':raise E('OBJECT_HASH')
    after=probe(target,kind,size,oid)
    if after!=before:raise E('REPAIR_FILE_CHANGED')
    os.replace(temp,target);emit('repair_file.replaced')
    sync_dir(outdir);sync_dir(stage);emit('repair_file.durable')
    if probe(target,kind,size,oid)[0]!='valid':raise E('OBJECT_HASH')
