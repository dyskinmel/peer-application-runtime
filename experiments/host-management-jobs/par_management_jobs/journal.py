"""Single bounded signed-file journal per job. No second-database atomicity claim."""
import os,re,tempfile,threading
from pathlib import Path
from par_store.fs import safe,WriterLock,sync_dir
from par_recovery.transfer import mkdir,read_file
from par_keeper_upload.spool import private
from . import contract as c
E=c.E
class Journal:
    def __init__(self,backend,root,*,max_jobs=c.MAX_JOBS,max_bytes=c.MAX_TOTAL,observer=None):
        self.backend=backend;self.root=safe(Path(root));self.p=backend.p;self.k=backend.k
        self.owner=(os.getpid(),threading.get_ident());self.closed=True;self.poison=False;self.lock=None
        self.busy=False;self.observer=observer;self.seen={}
        c.integer(max_jobs,1,c.MAX_JOBS);c.integer(max_bytes,4096,c.MAX_TOTAL)
        self.config={0:1,1:c.PROFILE,2:self.k.public,3:backend.g.store_id,4:max_jobs,5:max_bytes}
        for other in (backend.g.root,self.k.root):
            other=Path(other)
            if self.root==other or self.root in other.parents or other in self.root.parents:raise E('JOB_PATH_SCOPE')
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root)
            path=self.root/'CONFIG.cbor'
            if path.exists():
                private(path)
                if c.dump(c.load(read_file(path,4096)))!=c.dump(self.config):raise E('JOB_SETTINGS')
            else:
                if any(p.name!='.store.lock' for p in self.root.iterdir()):raise E('JOB_SETTINGS')
                self.atomic(path,c.dump(self.config),'init')
            self.closed=False;self.audit()
            # Unacknowledged temp journals do not execute anything. Keep them for
            # diagnosis; one file allocation remains separately bounded below.
        except BaseException:self.close();raise
    def close(self):
        if self.lock is not None:
            if self.owner!=(os.getpid(),threading.get_ident()):raise E('OWNER_REQUIRED')
            self.lock.close();self.lock=None
        self.closed=True
    def guard(self):
        if self.owner!=(os.getpid(),threading.get_ident()) or self.busy:raise E('OWNER_REQUIRED')
        if self.closed:raise E('CLOSED')
        if self.poison:raise E('RECOVERY_REQUIRED')
        if self.backend.g.closed or self.k._closed:raise E('CLOSED')
        private(self.root,True);private(self.root/'CONFIG.cbor')
        if c.dump(c.load(read_file(self.root/'CONFIG.cbor',4096)))!=c.dump(self.config):raise E('JOB_SETTINGS')
    def emit(self,name):
        if self.observer:self.observer('job.'+name)
    def path(self,jid):c.fixed(jid);return self.root/(jid.hex()+'.job')
    def atomic(self,path,raw,label):
        private(self.root,True)
        # Excludes filesystem metadata/temporary overhead from logical quota.
        leftovers=list(self.root.glob('.job-*.tmp'))
        if sum(p.stat().st_size for p in leftovers)+len(raw)>2*c.MAX_FILE:raise E('JOB_TEMP_CAPACITY')
        fd,name=tempfile.mkstemp(prefix='.job-',suffix='.tmp',dir=self.root);tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();self.emit(label+'.before_fsync');os.fsync(f.fileno())
            self.emit(label+'.before_replace');safe(path)
            if path.exists():private(path)
            os.replace(tmp,path);self.emit(label+'.after_replace');sync_dir(self.root)
            self.emit(label+'.after_sync')
        except OSError:
            self.poison=True;raise E('JOB_JOURNAL_UNCERTAIN') from None
        except BaseException:
            self.poison=True;raise
        finally:
            if tmp.exists():
                try:tmp.unlink()
                except OSError:pass
    def audit(self):
        self.guard();rows=[]
        for path in sorted(self.root.iterdir()):
            private(path)
            if path.name in ('CONFIG.cbor','.store.lock'):continue
            if re.fullmatch(r'\.job-[a-zA-Z0-9_-]+\.tmp',path.name):continue
            if not re.fullmatch(r'[0-9a-f]{64}\.job',path.name):raise E('JOB_LAYOUT')
            b,a,raw=self.read(bytes.fromhex(path.stem));rows.append((b,a,len(raw)))
        if not set(self.seen)<={b[4] for b,_,_ in rows}:raise E('JOB_JOURNAL_CHANGED')
        if len(rows)>self.config[4] or sum(n for _,_,n in rows)>self.config[5]:raise E('JOB_CAPACITY')
        return rows
    def read(self,jid):
        path=self.path(jid)
        if not path.exists():raise E('JOB_NOT_FOUND')
        private(path);raw=read_file(path,c.MAX_FILE);b,a=c.unpack(self.p,self.k.public,raw)
        if (b[3],b[4])!=(self.backend.g.store_id,jid):raise E('JOB_SCOPE')
        if jid in self.seen and self.seen[jid]!=c.sha(raw):raise E('JOB_JOURNAL_CHANGED')
        self.seen[jid]=c.sha(raw);return b,a,raw
    def persist(self,b,archive,label):
        raw=c.pack(self.p,self.k._seed,b,archive)
        # Reserve event growth so a full queue cannot strand an accepted job.
        if len(raw)>c.MAX_FILE:raise E('JOB_CAPACITY')
        self.atomic(self.path(b[4]),raw,label);self.seen[b[4]]=c.sha(raw)
    def transition(self,b,archive,state,result=None,witness=None):
        # Do not mutate the caller's snapshot until the new record is durable.
        updated=c.load(c.dump(b));events=updated[13]
        events.append({0:len(events),1:state,2:result,3:witness})
        c.shape(updated,archive);self.persist(updated,archive,state.lower());return updated
