"""Issuer-controlled upload windows; durable admission barrier before record cleanup.

Only the current private spool is compacted. Signed audit archives are retained
under a separate bounded budget. No Keeper mutations, automatic rollover, TTL,
public listeners or whole-store rollback guarantee. The caller/host is trusted
and must never bypass this gateway to call the internal schema2 spool directly.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import re
import tempfile
import threading

from par_store.fs import safe, sync_dir, WriterLock
from par_recovery.transfer import mkdir, read_file
from par_recovery.contract import object_id
from par_keeper.contract import authority_body, dump as kd, split, load as kl
from par_keeper_upload import protocol as u
from par_keeper_upload.spool import private, MAX_BYTES, MAX_RECORDS
from par_keeper_upload_retire.spool import RetiringSpool
from . import contract as c
E=c.E


class ReplaySpool:
    def __init__(self, keeper, root, store_id, *, max_bytes=MAX_BYTES,
                 max_records=MAX_RECORDS, max_archive_bytes=c.MAX_ARCHIVES,
                 max_windows=c.MAX_WINDOWS, expected_pin=None, observer=None):
        self.keeper=keeper;self.provider=keeper.provider;self.root=safe(Path(root));self.store_id=store_id
        self.observer=observer;self.thread=threading.get_ident();self.lock=None;self.live_lock=None
        self._inner=None;self.closed=True;self.poison=False;self.busy=False;self._last_raw=None
        c.fixed(store_id);c.integer(max_bytes,1,MAX_BYTES);c.integer(max_records,1,MAX_RECORDS)
        c.integer(max_archive_bytes,1,c.MAX_ARCHIVES);c.integer(max_windows,1,c.MAX_WINDOWS)
        if keeper._closed or keeper._thread!=self.thread:raise E('OWNER_REQUIRED')
        self.config={0:3,1:c.PROFILE,2:keeper.public,3:store_id,4:max_bytes,5:max_records,6:max_archive_bytes,7:max_windows}
        self.live=self.root/'live';self.bindings=self.root/'bindings';self.archives=self.root/'archives'
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root)
            cfg=self.root/'LIMITS.cbor'
            if cfg.exists():
                private(cfg)
                if c.load(read_file(cfg,4096))!=self.config:raise E('WINDOW_SETTINGS_OR_LEGACY')
            else:
                if any(p.name!='.store.lock' for p in self.root.iterdir()):raise E('WINDOW_SETTINGS_OR_LEGACY')
                self._atomic(cfg,c.dump(self.config),'window.init_config')
            for p in (self.live,self.bindings,self.archives):mkdir(p);private(p,True)
            sync_dir(self.root)
            if not (self.root/'STATE.cbor').exists():
                if any(p.name!='.store.lock' for d in (self.live,self.bindings,self.archives) for p in d.iterdir()):raise E('WINDOW_STATE_MISSING')
                self._save({0:1,1:c.PROFILE,2:store_id,3:keeper.public,4:[]},'window.init_state')
            self.closed=False;self._read_state()
            if expected_pin is not None:self.verify_pin(expected_pin)
            self._layout()
            # Only unacknowledged atomic-temp files in the private root are cleaned.
            for p in self.root.glob('.window-*.tmp'):private(p);p.unlink()
            sync_dir(self.root)
            if self.phase=='OPEN':self._open_inner()
            else:self.live_lock=WriterLock(self.live)
            self._audit_live()
        except BaseException:self.close();raise

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if self._inner is not None:self._inner.close();self._inner=None
        if self.live_lock is not None:self.live_lock.close();self.live_lock=None
        if self.lock is not None:self.lock.close();self.lock=None
        self.closed=True
    @property
    def row(self):return self.state[4][-1] if self.state[4] else None
    @property
    def phase(self):return self.row[1] if self.row else 'EMPTY'
    @property
    def window(self):return self.row[0] if self.row else None
    def _emit(self,event):
        if self.observer:self.observer(event)
    def _atomic(self,path,raw,label):
        if type(raw) is not bytes or not raw or len(raw)>c.MAX_ARCHIVE:raise E('WINDOW_SIZE')
        private(path.parent,True)
        fd,name=tempfile.mkstemp(prefix='.window-',suffix='.tmp',dir=self.root);tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            self._emit(label+'.before_replace');safe(path)
            if path.exists():private(path)
            os.replace(tmp,path);self._emit(label+'.after_replace')
            sync_dir(path.parent)
            if path.parent!=self.root:sync_dir(self.root)
            self._emit(label+'.after_sync')
        except BaseException:self.poison=True;raise
        finally:
            if tmp.exists():tmp.unlink()
    def _save(self,state,label):
        raw=c.signed(self.provider,self.keeper._seed,'state',state)
        self._atomic(self.root/'STATE.cbor',raw,label)
        self.state=c.load(c.dump(state));self._last_raw=raw
    def _archive_path(self,sequence):return self.archives/f'{sequence:08d}.cbor'
    def _read_state(self):
        p=self.root/'STATE.cbor';private(p);raw=read_file(p,c.MAX_CONTROL)
        if self._last_raw is not None and raw!=self._last_raw:raise E('WINDOW_STATE_CHANGED')
        b=c.verified(self.provider,raw,'state',self.keeper.public);c.keys(b,range(5));c.version(b)
        if (b[2],b[3])!=(self.store_id,self.keeper.public):raise E('WINDOW_SCOPE')
        if type(b[4]) is not list or len(b[4])>self.config[7]:raise E('WINDOW_STATE')
        previous=None;last_authority=None;nonces=set()
        for number,row in enumerate(b[4],1):
            c.keys(row,range(5));w=c.check_window(self.provider,row[0])
            if (w[3],w[4],w[5],w[7])!=(self.keeper.public,self.store_id,number,previous) or w[6] in nonces:raise E('WINDOW_ORDER')
            nonces.add(w[6])
            if last_authority is not None:c.r._authority_order(last_authority,w[2])
            if row[1] not in ('OPEN','CLOSED','CLEANED'):raise E('WINDOW_STATE')
            if number<len(b[4]) and row[1]!='CLEANED':raise E('WINDOW_ORDER')
            if row[1]=='OPEN':
                if any(row[k] is not None for k in (2,3,4)):raise E('WINDOW_STATE')
                last_authority=w[2]
            else:
                q=c.check_close(self.provider,row[0],row[2],row[3]);last_authority=q[2]
                if row[1]=='CLOSED':
                    if row[4] is not None:raise E('WINDOW_STATE')
                else:
                    rec=c.verified(self.provider,row[4],'cleaned',self.keeper.public)
                    c.keys(rec,range(8));c.version(rec);c.integer(rec[5],0,MAX_RECORDS)
                    if rec[6] is not False or rec[7] is not False:raise E('WINDOW_RECEIPT')
                    if (rec[2],rec[3],rec[4],rec[6],rec[7])!=(c.digest(row[0]),c.digest(row[2]),row[3],False,False):raise E('WINDOW_RECEIPT')
                    previous=c.digest(row[4])
        self.state=b;self._last_raw=raw
    def _layout(self):
        for d in (self.root,self.live,self.bindings,self.archives):private(d,True)
        private(self.root/'LIMITS.cbor')
        if c.load(read_file(self.root/'LIMITS.cbor',4096))!=self.config:raise E('WINDOW_SETTINGS_OR_LEGACY')
        for p in self.root.iterdir():
            if p.name in ('live','bindings','archives'):continue
            private(p)
            if p.name not in ('.store.lock','LIMITS.cbor','STATE.cbor') and not re.fullmatch(r'\.window-[a-zA-Z0-9_-]+\.tmp',p.name):raise E('WINDOW_LAYOUT')
        expected=set();total=0
        for i,row in enumerate(self.state[4],1):
            p=self._archive_path(i)
            if row[1]=='OPEN' and not p.exists():continue
            if not p.exists():raise E('ARCHIVE_MISSING')
            private(p);raw=read_file(p,c.MAX_ARCHIVE);a=c.check_archive(self.provider,raw,row[0])
            if row[1]!='OPEN' and c.digest(raw)!=row[3]:raise E('ARCHIVE_CHANGED')
            if row[1]=='CLEANED':
                rec=c.verified(self.provider,row[4],'cleaned',self.keeper.public)
                if rec[5]!=a[6]:raise E('WINDOW_RECEIPT')
            expected.add(p.name);total+=len(raw)
        if {p.name for p in self.archives.iterdir()}!=expected or total>self.config[6]:raise E('ARCHIVE_SET')
    def _enter(self):
        if self.closed or self.keeper._closed:raise E('CLOSED')
        if self.thread!=threading.get_ident() or self.busy:raise E('OWNER_REQUIRED')
        if self.poison:raise E('RECOVERY_REQUIRED')
        self._read_state();self._layout()
    @contextmanager
    def _operation(self):
        self._enter();self.busy=True
        try:yield
        except OSError:
            self.poison=True;raise E('OUTCOME_UNKNOWN') from None
        finally:self.busy=False
    def _current(self,authority=None):
        k=self.keeper
        with k._operation():
            actual=authority_body(k.authority)
            if k.connection.execute('SELECT authority FROM metadata').fetchone()[0]!=kd(actual):raise E('STALE_AUTHORITY')
            if authority is not None and actual!=authority:raise E('STALE_AUTHORITY')
            if self.window is not None:c.r._authority_order(c.check_window(self.provider,self.window)[2],actual)
        return actual
    def _open_inner(self):
        if self.live_lock is not None:self.live_lock.close();self.live_lock=None
        self._inner=RetiringSpool(self.keeper,self.live,max_bytes=self.config[4],max_records=self.config[5],observer=self._emit)
    def _detach_inner(self):
        if self._inner is not None:
            self.live_lock=self._inner.lock;self._inner.lock=None;self._inner.close();self._inner=None
    def _files(self):
        out=[]
        for directory in (self.live,self.bindings):
            for p in directory.iterdir():
                private(p)
                if directory==self.live and p.name in ('.store.lock','LIMITS.cbor'):continue
                suffix=r'\.(cbor|retirement)' if directory==self.live else r'\.bound'
                if not re.fullmatch('[0-9a-f]{64}'+suffix,p.name):raise E('WINDOW_RECORD_SET')
                out.append(p)
        return sorted(out,key=lambda p:p.relative_to(self.root).as_posix())
    def _capture(self,path):
        private(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            before=os.fstat(fd)
            if before.st_size>c.MAX_CONTROL:raise E('WINDOW_SIZE')
            with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(c.MAX_CONTROL+1)
            after=os.fstat(fd)
            identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            if identity(before)!=identity(after) or len(raw)!=before.st_size:raise E('WINDOW_RECORD_CHANGED')
            return [path.relative_to(self.root).as_posix(),len(raw),hashlib.sha256(raw).digest(),before.st_dev,before.st_ino,raw]
        finally:os.close(fd)
    def _binding(self,t):return self.bindings/(t.hex()+'.bound')
    def _audit_live(self):
        if self.phase in ('EMPTY','CLEANED'):
            if self._files():raise E('WINDOW_DATA_REAPPEARED')
        elif self.phase=='CLOSED':self._remaining(self._archive())
        else:
            # Child recovery validates .part files; binding records only add admission scope.
            tokens={p.stem for p in self.live.glob('*.cbor') if p.name!='LIMITS.cbor'}
            bound={p.stem for p in self.bindings.glob('*.bound')}
            if not tokens<=bound or len(bound)>self.config[5]:raise E('WINDOW_BINDING_SET')
            for path in self.bindings.iterdir():
                private(path)
                if not re.fullmatch(r'[0-9a-f]{64}\.bound',path.name):raise E('WINDOW_BINDING_SET')
                raw=read_file(path,c.MAX_CONTROL);b=c.check_command(self.provider,self.window,raw)
                if b[3]!='execute' or u.check_command(self.provider,b[4])[2]!='begin' or u.token_for(self.provider,b[4]).hex()!=path.stem:raise E('WINDOW_BINDING_SET')
                p=self.live/(path.stem+'.cbor')
                if p.exists():
                    m=u.load(read_file(p,c.MAX_CONTROL),c.MAX_CONTROL)
                    if m[2]!=b[4]:raise E('WINDOW_BINDING_SET')
    def open_window(self,grant):
        with self._operation():
            w=c.check_window(self.provider,grant);self._current(w[2]);self._audit_live()
            if self.phase=='OPEN':
                if self.window!=grant:raise E('WINDOW_ALREADY_OPEN')
                return self.pin()
            if self.phase not in ('EMPTY','CLEANED'):raise E('WINDOW_NOT_CLEANED')
            previous=None if not self.row else c.digest(self.row[4])
            if (w[3],w[4],w[5],w[7])!=(self.keeper.public,self.store_id,len(self.state[4])+1,previous):raise E('WINDOW_ORDER')
            if len(self.state[4])>=self.config[7] or any(c.check_window(self.provider,r[0])[6]==w[6] for r in self.state[4]):raise E('WINDOW_LIMIT')
            if self.row:c.r._authority_order(c.check_close(self.provider,self.row[0],self.row[2])[2],w[2])
            state=c.load(c.dump(self.state));state[4].append({0:grant,1:'OPEN',2:None,3:None,4:None})
            self._emit('window.open.before_commit');self._current(w[2]);self._save(state,'window.open')
            self._open_inner();return self.pin()
    def _admit(self,raw):
        if self.phase!='OPEN':raise E('WINDOW_CLOSED')
        if self._archive_path(len(self.state[4])).exists():raise E('WINDOW_CLOSE_PREPARED')
        b=c.check_command(self.provider,self.window,raw);self._current();self._audit_live()
        return b
    def execute(self,raw):
        with self._operation():
            b=self._admit(raw);kind,inner=b[3],b[4]
            if kind!='execute':
                self._prepare_unstarted_retirement(inner,kind)
                return getattr(self._inner,kind)(inner)
            command=u.check_command(self.provider,inner)
            if command[2]=='begin':
                self._inner.stamp(inner)  # Includes current underlying capability check.
                t=u.token_for(self.provider,inner);path=self._binding(t)
                if path.exists():
                    if read_file(path,c.MAX_CONTROL)!=raw:raise E('OPERATION_CONFLICT')
                else:
                    self._admission_capacity(raw,command)
                    self._emit('window.bind.before_commit');self._inner.stamp(inner)
                    self._admission_capacity(raw,command)
                    self._atomic(path,raw,'window.bind')
            elif command[2]!='seal':
                t=command[7][0] if command[2] in ('chunk','reserve') else command[7]
                if not self._binding(t).exists():raise E('STAGE_UNKNOWN')
            return self._inner.execute(inner)
    def _archive_reservation(self,raw):
        body=c.check_command(self.provider,self.window,raw)
        # Bound the largest of terminal finalized metadata or 8-grant retirement
        # journal, plus original begin, outer binding and signed manifest framing.
        return len(raw)+len(body[4])+c.r.MAX_BYTES+4096
    def _admission_capacity(self,raw,command):
        records=self._inner.diagnostics()
        if (len(list(self.bindings.iterdir()))>=self.config[5]
                or records['reserved_bytes']+command[7][2]>self.config[4]):raise E('STAGING_CAPACITY')
        if command[6] is not None and self.keeper._lease(command[6])['state']!='reserved':raise E('NOT_UPLOADING')
        needed=self._archive_reservation(raw)+sum(self._archive_reservation(read_file(p,c.MAX_CONTROL)) for p in self.bindings.iterdir())
        spent=sum(p.stat().st_size for p in self.archives.iterdir())
        if needed>min(c.MAX_ARCHIVE-4096,self.config[6]-spent):raise E('ARCHIVE_CAPACITY')
    def _prepare_unstarted_retirement(self,inner,kind):
        request,_,grant=c.r.inspect_request(self.provider,inner)
        token=grant[5];boundpath=self._binding(token)
        if not boundpath.exists():raise E('STAGE_UNKNOWN')
        bound=c.check_command(self.provider,self.window,read_file(boundpath,c.MAX_CONTROL))
        begin=bound[4];self._inner._authorize(inner,begin)
        target=self.live/(token.hex()+'.cbor')
        if target.exists():return
        if kind!='retire':raise E('RETIREMENT_NOT_PENDING')
        # Crash after binding but before the schema2 begin ACK: no acknowledged
        # upload exists. Materialize only an empty abandoned origin, authorized by
        # the current retirement grant, not by the now-stale upload capability.
        part=self.live/(token.hex()+'.part')
        if part.exists():
            private(part)
            if part.stat().st_size!=0:raise E('WINDOW_RECORD_CHANGED')
        else:
            fd=os.open(part,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            try:os.fsync(fd)
            finally:os.close(fd)
        self._emit('window.abandon.authorized');self._inner._authorize(inner,begin)
        m={0:1,1:token,2:begin,3:0,4:hashlib.sha256(b'').digest(),5:'active',6:None,7:None}
        self._inner._atomic(target,m,'window.abandon')

    def stamp(self,raw):
        with self._operation():
            b=self._admit(raw)
            if b[3]!='execute':raise E('WINDOW_METHOD')
            return c.digest(self.window),self._inner.stamp(b[4])
    def _terminal_entries(self):
        self._audit_live()
        records=self._inner._records();bound={p.stem for p in self.bindings.iterdir()}
        if {m[1].hex() for m,b in records}!=bound:raise E('WINDOW_NOT_TERMINAL')
        for m,b in records:
            t=m[1]
            if m[5]=='retired':
                self._inner._validate_journal(t)
            elif m[5]=='committed':
                # Recheck confirmed handoff using read-only Keeper evidence. No retry mutation.
                f=u.check_command(self.provider,m[6]);k=self.keeper
                with k._operation():
                    if f[2]=='reserve':
                        req=split(f[5])[0]
                        if k._cached(req,f[4],f[5])!=m[7]:raise E('HANDOFF_NOT_VERIFIED')
                    else:
                        row=k._lease(f[6]);oid=m[7]
                        if k.connection.execute('SELECT 1 FROM stored_objects WHERE lease=? AND oid=?',(f[6],oid)).fetchone() is None:raise E('HANDOFF_NOT_VERIFIED')
                        data=read_file(k.object_path(f[6],oid),u.MAX_OBJECT)
                        if len(data)!=b[7][2] or hashlib.sha256(data).digest()!=b[7][3]:raise E('HANDOFF_NOT_VERIFIED')
            else:raise E('WINDOW_NOT_TERMINAL')
            if self._inner._path(t,'.part').exists():raise E('WINDOW_NOT_TERMINAL')
        files=self._files()
        if sum(p.stat().st_size for p in files)>c.MAX_ARCHIVE-65536:raise E('ARCHIVE_CAPACITY')
        return [self._capture(p) for p in files],len(records)
    def export_archive(self):
        with self._operation():
            if self.phase!='OPEN':raise E('WINDOW_CLOSED')
            self._current();entries,count=self._terminal_entries();w=c.check_window(self.provider,self.window)
            raw=c.sign_archive(self.provider,self.keeper._seed,{0:1,1:c.PROFILE,2:c.digest(self.window),3:self.store_id,4:w[5],5:entries,6:count})
            c.check_archive(self.provider,raw,self.window);return raw
    def close_window(self,request,archive):
        with self._operation():
            if self.window is None:raise E('WINDOW_CLOSED')
            a=c.check_archive(self.provider,archive,self.window)
            q=c.check_close(self.provider,self.window,request,c.digest(archive))
            if self.phase in ('CLOSED','CLEANED'):
                if self.row[2]!=request or self.row[3]!=c.digest(archive):raise E('CLOSE_CONFLICT')
                return self.pin()
            self._current(q[2]);entries,count=self._terminal_entries()
            if [entries,count]!=[a[5],a[6]]:raise E('ARCHIVE_CHANGED')
            path=self._archive_path(len(self.state[4]));other=sum(p.stat().st_size for p in self.archives.iterdir() if p!=path)
            if len(archive)+other>self.config[6]:raise E('ARCHIVE_CAPACITY')
            if path.exists() and read_file(path,c.MAX_ARCHIVE)!=archive:raise E('ARCHIVE_CHANGED')
            self._atomic(path,archive,'window.archive');self._emit('window.close.before_barrier')
            self._current(q[2]);entries2,count2=self._terminal_entries()
            if [entries2,count2]!=[a[5],a[6]]:raise E('ARCHIVE_CHANGED')
            state=c.load(c.dump(self.state));state[4][-1].update({1:'CLOSED',2:request,3:c.digest(archive)})
            self._save(state,'window.close');self._detach_inner();return self.pin()
    def _archive(self):
        raw=read_file(self._archive_path(len(self.state[4])),c.MAX_ARCHIVE)
        if c.digest(raw)!=self.row[3]:raise E('ARCHIVE_CHANGED')
        return c.check_archive(self.provider,raw,self.window)
    def _remaining(self,archive):
        expected={entry[0]:entry for entry in archive[5]}
        for p in self._files():
            rel=p.relative_to(self.root).as_posix()
            if rel not in expected or self._capture(p)!=expected[rel]:raise E('WINDOW_RECORD_CHANGED')
    def compact(self):
        with self._operation():
            if self.phase=='CLEANED':self._audit_live();return self.row[4]
            if self.phase!='CLOSED':raise E('WINDOW_NOT_CLOSED')
            a=self._archive();self._remaining(a)
            for entry in a[5]:
                path=safe(self.root/entry[0]);self._emit('window.compact.before_unlink')
                if path.exists():
                    if self._capture(path)!=entry:raise E('WINDOW_RECORD_CHANGED')
                    path.unlink();self._emit('window.compact.after_unlink')
                sync_dir(path.parent);self._emit('window.compact.after_unlink_sync')
            self._emit('window.compact.before_credit');self._remaining(a)
            if self._files():raise E('WINDOW_RECORD_CHANGED')
            sync_dir(self.live);sync_dir(self.bindings)
            receipt=c.signed(self.provider,self.keeper._seed,'cleaned',{0:1,1:c.PROFILE,2:c.digest(self.window),3:c.digest(self.row[2]),4:self.row[3],5:a[6],6:False,7:False})
            state=c.load(c.dump(self.state));state[4][-1].update({1:'CLEANED',4:receipt})
            self._save(state,'window.compact');self._emit('window.compact.ack');return receipt
    def pin(self):
        # A caller must store this outside the rollback domain. It is not auto trusted.
        return {0:self.store_id,1:len(self.state[4]),2:c.digest(self.window) if self.window else None,
                3:c.digest(self.row[2]) if self.row and self.row[2] else None}
    def verify_pin(self,pin):
        c.keys(pin,range(4));c.fixed(pin[0]);c.integer(pin[1],0,self.config[7])
        if pin[0]!=self.store_id or pin[1]>len(self.state[4]):raise E('WINDOW_PIN')
        if pin[1]==0:
            if pin[2] is not None or pin[3] is not None:raise E('WINDOW_PIN')
        else:
            c.fixed(pin[2]);row=self.state[4][pin[1]-1]
            if pin[2]!=c.digest(row[0]):raise E('WINDOW_PIN')
            if pin[3] is not None:
                c.fixed(pin[3])
                if row[2] is None or pin[3]!=c.digest(row[2]):raise E('WINDOW_PIN')
        return True
    def diagnostics(self):
        self._enter();self._audit_live()
        if self.phase=='OPEN':
            d=self._inner.diagnostics();records=len(list(self.bindings.iterdir()));reserved=d['reserved_bytes']
        elif self.phase=='CLOSED':records=self._archive()[6];reserved=0
        else:records=0;reserved=0
        return {'phase':self.phase,'sequence':len(self.state[4]),'records':records,'reserved_bytes':reserved,
                'max_records':self.config[5],'archive_bytes':sum(p.stat().st_size for p in self.archives.iterdir()),
                'archives':len(list(self.archives.iterdir())),'record_quota_reclaimed':self.phase=='CLEANED',
                'physical_space_reclaimed':False,'keeper_mutated':False,'product_qualified':False}
