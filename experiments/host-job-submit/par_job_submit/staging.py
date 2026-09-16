"""Bounded owner-only staging, crash-aware registration, no automatic dispatch.

Payloads and signed stage receipts are retained under a finite budget. This is
not an atomic transaction with ManagementJobs, an OS sandbox, or an anti-rollback
root. Reconciliation reads the exact registered job before explicit retry.
"""
from __future__ import annotations
import os,re,tempfile,threading
from pathlib import Path
from contextlib import contextmanager
from par_store.fs import safe,WriterLock,sync_dir
from par_recovery.transfer import mkdir,read_file
from par_keeper_upload.spool import private
from par_management_jobs import contract as j
from . import protocol as c
E=c.E

def context_hash(authority,pin,phase,window):return c.sha(j.dump([authority,pin,phase,window]))

class Submissions:
    def __init__(self,controller,root,*,max_records=c.MAX_RECORDS,max_bytes=c.MAX_TOTAL,observer=None):
        controller.host._guard();c.integer(max_records,1,c.MAX_RECORDS);c.integer(max_bytes,1024,c.MAX_TOTAL)
        self.ctl=controller;self.host=controller.host;self.jobs=self.host.jobs;self.k=self.host.keeper;self.p=self.k.provider
        self.root=safe(Path(root));self.owner=(os.getpid(),threading.get_ident());self.closed=True;self.poison=False;self.busy=False
        self.observer=observer;self.lock=None;self.seen={}
        self.config={0:1,1:c.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:max_records,5:max_bytes}
        for p in (self.k.root,self.host.gateway.root,self.jobs.journal.root,self.ctl.journal.root):
            p=Path(p)
            if self.root==p or p in self.root.parents or self.root in p.parents:raise E('SUBMIT_PATH_SCOPE')
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root)
            cfg=self.root/'CONFIG.cbor'
            if cfg.exists():
                private(cfg)
                if c.dump(c.load(read_file(cfg,4096),4096),4096)!=c.dump(self.config,4096):raise E('SUBMIT_SETTINGS')
            else:
                if any(p.name!='.store.lock' for p in self.root.iterdir()):raise E('SUBMIT_SETTINGS')
                self._atomic(cfg,c.dump(self.config,4096),'init')
            self.closed=False;self.audit()
        except BaseException:self.close();raise
    def close(self):
        if self.lock is not None:
            if self.owner!=(os.getpid(),threading.get_ident()):raise E('SUBMIT_OWNER')
            self.lock.close();self.lock=None
        self.closed=True
    def guard(self):
        if self.owner!=(os.getpid(),threading.get_ident()) or self.busy:raise E('SUBMIT_OWNER')
        if self.closed:raise E('CLOSED')
        if self.poison:raise E('SUBMIT_REOPEN_REQUIRED')
        self.host._guard();private(self.root,True);private(self.root/'CONFIG.cbor')
        if self.k.provider is not self.p:raise E('SUBMIT_PROVIDER')
        if c.dump(c.load(read_file(self.root/'CONFIG.cbor',4096),4096),4096)!=c.dump(self.config,4096):raise E('SUBMIT_SETTINGS')
    @contextmanager
    def operation(self):
        self.audit();self.busy=True
        try:yield
        finally:self.busy=False
    def emit(self,n):
        if self.observer:self.observer('submit.'+n)
    def payload_path(self,jid):c.fixed(jid);return self.root/(jid.hex()+'.payload')
    def _path(self,jid):c.fixed(jid);return self.root/(jid.hex()+'.stage')
    def _atomic(self,path,raw,label):
        private(self.root,True)
        leftovers=list(self.root.glob('.submit-*.tmp'))
        for p in leftovers:private(p)
        if sum(p.stat().st_size for p in leftovers)+len(raw)>2*c.MAX_RECORD:raise E('SUBMIT_TEMP_CAPACITY')
        fd,name=tempfile.mkstemp(prefix='.submit-',suffix='.tmp',dir=self.root);tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();self.emit(label+'.before_fsync');os.fsync(f.fileno())
            self.emit(label+'.before_replace');safe(path)
            if path.exists():private(path)
            os.replace(tmp,path);self.emit(label+'.after_replace');sync_dir(self.root);self.emit(label+'.after_sync')
        except OSError:
            self.poison=True;raise E('SUBMIT_JOURNAL_UNCERTAIN') from None
        except BaseException:
            self.poison=True;raise
        finally:
            if tmp.exists():
                try:tmp.unlink()
                except OSError:pass
    def _persist(self,m,label):
        raw=c.signed(self.p,self.k._seed,'stage',m,c.MAX_RECORD)
        self._atomic(self._path(c.check_descriptor(self.p,m[4])[5]),raw,label)
        self.seen[c.check_descriptor(self.p,m[4])[5]]=c.sha(raw)
    def _read(self,jid):
        path=self._path(jid)
        if not path.exists():raise E('SUBMIT_NOT_FOUND')
        private(path);raw=read_file(path,c.MAX_RECORD);m,o=c.split(raw,c.MAX_RECORD);c.keys(m,range(10));c.version(m);c.verify(self.p,self.k.public,o,'stage')
        d=c.check_descriptor(self.p,m[4])
        if (m[2],m[3],d[2],d[3],d[5])!=(self.k.public,self.host.gateway.store_id,self.k.public,self.host.gateway.store_id,jid):raise E('SUBMIT_SCOPE')
        c.integer(m[5],0,d[7]);c.fixed(m[6]);c.integer(m[8],0,2**53-1)
        if type(m[7]) is not str or m[7] not in c.STATES:raise E('SUBMIT_STATE')
        if m[7]!='RECEIVING' and (m[5],m[6])!=(d[7],d[8]):raise E('SUBMIT_STATE')
        if (m[9] is not None)!=(m[7]=='REGISTERED'):raise E('SUBMIT_STATE')
        if m[9] is not None:c.fixed(m[9])
        if jid in self.seen and c.sha(raw)!=self.seen[jid]:raise E('SUBMIT_CHANGED')
        self.seen[jid]=c.sha(raw);self._payload(m,d)
        return m,d
    def _payload(self,m,d):
        path=self.payload_path(d[5]);safe(path)
        if not path.exists():
            if m[5]:raise E('SUBMIT_MISSING')
            raw=b''
        else:
            private(path);raw=read_file(path,d[7])
        if len(raw)<m[5] or c.sha(raw[:m[5]])!=m[6]:raise E('SUBMIT_HASH')
        if m[7]!='RECEIVING' and len(raw)!=m[5]:raise E('SUBMIT_HASH')
        return raw[:m[5]]
    def audit(self):
        self.guard();rows=[];payload_ids=set()
        for p in sorted(self.root.iterdir()):
            private(p)
            if p.name in ('CONFIG.cbor','.store.lock'):continue
            if re.fullmatch(r'\.submit-[A-Za-z0-9_-]+\.tmp',p.name):continue
            if re.fullmatch('[a-f0-9]{64}\\.payload',p.name):payload_ids.add(bytes.fromhex(p.stem));continue
            if not re.fullmatch('[a-f0-9]{64}\\.stage',p.name):raise E('SUBMIT_LAYOUT')
            rows.append(self._read(bytes.fromhex(p.stem)))
        ids={d[5] for m,d in rows}
        if not set(self.seen)<=ids or not payload_ids<=ids:raise E('SUBMIT_CHANGED')
        if len(rows)>self.config[4] or sum(d[7] for m,d in rows)>self.config[5]:raise E('SUBMIT_CAPACITY')
        return rows
    def diagnostics(self):
        rows=self.audit();return {'records':len(rows),'reserved_payload_bytes':sum(d[7] for m,d in rows),'maximum_records':self.config[4],'maximum_payload_bytes':self.config[5],'physical_disk_quota':False,'product_qualified':False}
    def target(self):
        self.guard();return context_hash(*self.jobs.backend.context())
    def context(self):
        self.audit();public,revision=self.ctl.policy()
        if public is None:raise E('STALE_CONTROLLER')
        return {'target_digest':self.target().hex(),'controller_revision':revision,'max_payload':c.MAX_PAYLOAD,'max_records':self.config[4],'product_qualified':False}
    def _descriptor(self,raw):
        d=c.check_descriptor(self.p,raw);public,revision=self.ctl.policy()
        if (d[2],d[3],d[4],d[9])!=(self.k.public,self.host.gateway.store_id,public,revision) or public is None:raise E('STALE_CONTROLLER')
        return d
    def _current(self,d):
        if context_hash(*self.jobs.backend.context())!=d[6]:raise E('SUBMIT_TARGET_CHANGED')
    def _matching(self,raw):
        d=self._descriptor(raw);m,_=self._read(d[5])
        if m[4]!=raw:raise E('SUBMIT_CONFLICT')
        return m,d
    def _view(self,m,d):
        if m[7]=='REGISTERED':
            fact=self._lookup(m,d)
            if fact is None or fact!=m[9]:raise E('SUBMIT_JOB_MISMATCH')
        v={'job_id':d[5].hex(),'state':m[7],'received':m[5],'total':d[7],'prefix_hash':m[6].hex(),'payload_hash':d[8].hex(),'target_digest':d[6].hex(),'registered_job_digest':m[9].hex() if m[9] else None,'automatically_selected':False,'product_qualified':False}
        c.view_shape(v);return v
    def begin(self,raw):
        with self.operation():
            d=self._descriptor(raw)
            if self._path(d[5]).exists():
                m,_=self._matching(raw);return self._view(m,d)
            self._current(d)
            existing=[self._read(bytes.fromhex(p.stem))[1] for p in self.root.glob('*.stage')]
            if len(existing)>=self.config[4] or sum(x[7] for x in existing)+d[7]>self.config[5]:raise E('SUBMIT_CAPACITY')
            rows=self.jobs.journal.audit()
            if len(rows)>=self.jobs.journal.config[4] and not self.jobs.journal.path(d[5]).exists():raise E('JOB_CAPACITY')
            m={0:1,1:c.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:raw,5:0,6:c.sha(b''),7:'RECEIVING',8:0,9:None}
            self._persist(m,'begin');return self._view(m,d)
    def progress(self,raw):
        with self.operation():m,d=self._matching(raw);return self._view(m,d)
    def chunk(self,raw,offset,data):
        c.integer(offset,0,c.MAX_PAYLOAD)
        if type(data) is not bytes or not 1<=len(data)<=c.CHUNK:raise E('SUBMIT_CHUNK')
        with self.operation():
            m,d=self._matching(raw);payload=self._payload(m,d)
            if offset<m[5]:
                if offset+len(data)>m[5]:raise E('SUBMIT_OFFSET')
                if payload[offset:offset+len(data)]!=data:raise E('SUBMIT_CONFLICT')
                return self._view(m,d)
            if m[7]!='RECEIVING':raise E('SUBMIT_CLOSED')
            self._current(d)
            if offset!=m[5] or offset+len(data)>d[7]:raise E('SUBMIT_OFFSET')
            content=payload+data
            if len(content)==d[7] and c.sha(content)!=d[8]:raise E('SUBMIT_HASH')
            path=self.payload_path(d[5]);safe(path)
            if path.exists():private(path)
            fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'r+b') as f:
                    f.truncate(m[5]);f.seek(m[5]);f.write(data);f.flush();self.emit('chunk.before_fsync');os.fsync(f.fileno())
                sync_dir(self.root);self.emit('chunk.after_payload_sync')
                self._descriptor(raw);self._current(d)
                m[5]=len(content);m[6]=c.sha(content);m[8]+=1
                if m[5]==d[7]:m[7]='READY'
                self._persist(m,'chunk');return self._view(m,d)
            except OSError:
                self.poison=True;raise E('SUBMIT_REOPEN_REQUIRED') from None
    def _input(self,m,d):
        payload=self._payload(m,d)
        if len(payload)!=d[7] or c.sha(payload)!=d[8]:raise E('SUBMIT_INCOMPLETE')
        return c.unpack_job(payload)
    def _lookup(self,m,d):
        self.jobs.journal.audit();path=self.jobs.journal.path(d[5])
        if not path.exists():return None
        action,command,archive=self._input(m,d);b,a,_=self.jobs.journal.read(d[5])
        if not j.input_equal(b,action,command,archive) or context_hash(b[9],b[10],b[11],b[12])!=d[6]:raise E('JOB_CONFLICT')
        self.jobs.poll(d[5]);return j.intent(b)
    def _preflight(self,m,d):
        self._descriptor(m[4]);self._current(d);action,command,archive=self._input(m,d)
        rows=self.jobs.journal.audit();needed=len(command or b'')+len(archive or b'')+262144
        if len(rows)>=self.jobs.journal.config[4] or sum(n+262144 for b,a,n in rows)+needed>self.jobs.journal.config[5]:raise E('JOB_CAPACITY')
        authority,pin,phase,window=self.jobs.backend.context()
        b={0:1,1:j.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:d[5],5:action,6:command,7:j.sha(archive) if archive else None,8:len(archive or b''),9:authority,10:pin,11:phase,12:window,13:[{0:0,1:'QUEUED',2:None,3:None}]}
        if any(j.intent(r[0])==j.intent(b) for r in rows):raise E('JOB_ALIAS')
        self.jobs.backend.validate(b,archive or b'')
        return action,command,archive
    def _registered(self,m,d,fact):
        m[7]='REGISTERED';m[9]=fact;m[8]+=1;self._persist(m,'registered');return self._view(m,d)
    def _dispatch(self,m,d):
        action,command,archive=self._preflight(m,d)
        m[7]='INFLIGHT';m[8]+=1;self._persist(m,'inflight')
        try:
            self.emit('before_dispatch');self._descriptor(m[4]);self._current(d)
            self.jobs.submit(d[5],action=action,command=command,archive=archive)
            self.emit('after_dispatch');self._descriptor(m[4])
            fact=self._lookup(m,d)
            if fact is None:raise E('SUBMIT_JOB_MISMATCH')
            return self._registered(m,d,fact)
        except Exception:raise E('SUBMIT_OUTCOME_UNKNOWN') from None
    def submit(self,raw):
        with self.operation():
            m,d=self._matching(raw)
            if m[7]=='REGISTERED':return self._view(m,d)
            if m[7]=='INFLIGHT':raise E('SUBMIT_RECONCILE_REQUIRED')
            if m[7]=='RETRY_READY':raise E('SUBMIT_EXPLICIT_RETRY')
            if m[7]!='READY':raise E('SUBMIT_INCOMPLETE')
            fact=self._lookup(m,d)
            if fact is not None:return self._registered(m,d,fact)
            return self._dispatch(m,d)
    def reconcile(self,raw):
        with self.operation():
            m,d=self._matching(raw)
            if m[7]=='REGISTERED':return self._view(m,d)
            if m[7] not in ('INFLIGHT','RETRY_READY'):raise E('SUBMIT_NOT_RECONCILABLE')
            fact=self._lookup(m,d)
            if fact is not None:return self._registered(m,d,fact)
            self._preflight(m,d)
            if m[7]!='RETRY_READY':m[7]='RETRY_READY';m[8]+=1;self._persist(m,'retry_ready')
            return self._view(m,d)
    def retry(self,raw):
        with self.operation():
            m,d=self._matching(raw)
            if m[7]!='RETRY_READY':raise E('SUBMIT_EXPLICIT_RETRY')
            fact=self._lookup(m,d)
            if fact is not None:return self._registered(m,d,fact)
            return self._dispatch(m,d)
    def execute(self,b):
        method=b[3]
        if method=='context':return self.context()
        if method=='chunk':return self.chunk(b[4],b[5],b[6])
        if method=='begin':return self.begin(b[4])
        if method=='progress':return self.progress(b[4])
        if method=='submit':return self.submit(b[4])
        if method=='reconcile':return self.reconcile(b[4])
        if method=='retry':return self.retry(b[4])
        raise E('SUBMIT_METHOD')
