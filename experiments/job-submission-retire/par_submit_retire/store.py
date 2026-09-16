"""Explicit, versioned retirement of submission payloads.

Original signed stages and dual-signed tombstones remain. Only the payload's
logical reservation is released; no job cancellation, record GC, secure erase,
whole-filesystem quota or cross-store atomicity is implied. Same cooperating
owner/process/thread as the existing submission store.
"""
from __future__ import annotations
import os,re,tempfile,threading
from pathlib import Path
from par_store.fs import safe,WriterLock,sync_dir
from par_recovery.transfer import mkdir,read_file
from par_keeper_upload.spool import private
from par_management_jobs import contract as j
from par_job_submit.staging import Submissions,context_hash
from par_job_submit import protocol as s
from . import contract as c
E=c.E

class RetiringSubmissions(Submissions):
    def __init__(self,controller,root,*,max_records=s.MAX_RECORDS,max_bytes=s.MAX_TOTAL,
                 observer=None,migrate_legacy=False,expected_pin=None):
        controller.host._guard();c.integer(max_records,1,s.MAX_RECORDS);c.integer(max_bytes,1024,s.MAX_TOTAL)
        if type(migrate_legacy) is not bool:raise E('RETIRE_SETTINGS')
        self.ctl=controller;self.host=controller.host;self.jobs=self.host.jobs;self.k=self.host.keeper;self.p=self.k.provider
        self.root=safe(Path(root));self.owner=(os.getpid(),threading.get_ident());self.closed=True
        self.poison=False;self.busy=False;self.observer=observer;self.lock=None;self.seen={};self.ret_seen={}
        self.config={0:2,1:c.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:max_records,5:max_bytes}
        for other in (self.k.root,self.host.gateway.root,self.jobs.journal.root,self.ctl.journal.root):
            other=Path(other)
            if self.root==other or other in self.root.parents or self.root in other.parents:raise E('SUBMIT_PATH_SCOPE')
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root);cfg=self.root/'CONFIG.cbor'
            if cfg.exists():
                private(cfg);found=s.load(read_file(cfg,4096),4096)
                if c.dump(found,4096)!=c.dump(self.config,4096):
                    legacy=dict(self.config);legacy[0]=1;legacy[1]=s.PROFILE
                    if c.dump(found,4096)!=c.dump(legacy,4096):raise E('RETIRE_SETTINGS')
                    if not migrate_legacy:raise E('RETIRE_MIGRATION_REQUIRED')
                    new=self.config;self.config=legacy;self.closed=False
                    Submissions.audit(self)  # Full old-format validation under the same exclusive lock.
                    self.config=new;self._atomic(cfg,c.dump(new,4096),'retire_migration')
            else:
                if any(p.name!='.store.lock' for p in self.root.iterdir()):raise E('RETIRE_SETTINGS')
                self._atomic(cfg,c.dump(self.config,4096),'retire_initialize')
            self.closed=False;self.audit()
            if expected_pin is not None:self.verify_pin(expected_pin)
        except BaseException:self.close();raise

    def retirement_path(self,jid):
        c.fixed(jid);return self.root/(jid.hex()+'.retire')

    def _source(self,jid):
        path=self._path(jid);private(path);return read_file(path,s.MAX_RECORD)

    def _snapshot_payload(self,d):
        path=self.payload_path(d[5]);safe(path)
        if not path.exists():return {0:False,1:0,2:c.sha(b''),3:None,4:None}
        private(path);before=path.stat();raw=read_file(path,d[7]);after=path.stat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise E('RETIRE_TARGET')
        return {0:True,1:len(raw),2:c.sha(raw),3:before.st_dev,4:before.st_ino}

    def _bound_job(self,m,d,fact):
        """Validate retained job input without depending on a deleted payload."""
        self.jobs.journal.audit();path=self.jobs.journal.path(d[5])
        if fact is None:
            if path.exists():raise E('RETIRE_JOB_MISMATCH')
            return
        if not path.exists():raise E('RETIRE_JOB_MISSING')
        b,archive,_=self.jobs.journal.read(d[5])
        payload=s.pack_job(b[5],b[6],archive or None)
        if (len(payload),c.sha(payload),context_hash(b[9],b[10],b[11],b[12]),j.intent(b))!=(d[7],d[8],d[6],fact):
            raise E('RETIRE_JOB_MISMATCH')
        self.jobs.poll(d[5])

    def _record(self,jid):
        path=self.retirement_path(jid);private(path);raw=read_file(path,c.MAX_JOURNAL)
        if jid in self.ret_seen and self.ret_seen[jid]!=c.sha(raw):raise E('RETIRE_CHANGED')
        b=c.unpack_record(self.p,self.k.public,raw)
        if (b[2],b[3],b[4])!=(self.k.public,self.host.gateway.store_id,jid) or b[5]!=self._source(jid):raise E('RETIRE_TARGET')
        m,o=s.split(b[5],s.MAX_RECORD);s.keys(m,range(10));s.version(m);s.verify(self.p,self.k.public,o,'stage')
        d=s.check_descriptor(self.p,m[4])
        if (d[2],d[3],d[5],m[2],m[3])!=(self.k.public,self.host.gateway.store_id,jid,self.k.public,self.host.gateway.store_id):raise E('RETIRE_TARGET')
        if m[7] not in ('RECEIVING','READY','RETRY_READY','REGISTERED'):raise E('RETIRE_STATE')
        if b[9]!=m[9] or ((b[9] is not None)!=(m[7]=='REGISTERED')):raise E('RETIRE_JOB_MISMATCH')
        last=None;last_revision=0
        history=self.ctl.journal.policy()[5]
        for request in b[7]:
            a=c.check_request(self.p,request)
            if (a[2],a[3],a[4],a[5],a[6],a[7],a[10],a[12])!=(b[2],b[3],jid,c.sha(m[4]),c.sha(b[5]),b[6],d[4],last):raise E('RETIRE_TARGET')
            if a[9]<=last_revision or [a[9],a[8]] not in history:raise E('RETIRE_POLICY_HISTORY')
            last_revision=a[9];last=c.sha(request)
        path=self.payload_path(jid);safe(path)
        if path.exists():
            if b[8]!='INTENT' or self._snapshot_payload(d)!=b[6]:raise E('RETIRE_PAYLOAD_CHANGED')
        self._bound_job(m,d,b[9]);self.ret_seen[jid]=c.sha(raw)
        return b,m,d

    def _payload(self,m,d):
        if self.retirement_path(d[5]).exists():
            b,_,_=self._record(d[5])
            if self.payload_path(d[5]).exists():return read_file(self.payload_path(d[5]),d[7])[:m[5]]
            return b''
        return super()._payload(m,d)

    def _reserved(self,rows):
        return sum(d[7] for m,d in rows if not self.retirement_path(d[5]).exists() or self._record(d[5])[0][8]!='TOMBSTONED')

    def audit(self):
        self.guard();rows=[];payload_ids=set();retired_ids=set();temp_bytes=0
        for path in sorted(self.root.iterdir()):
            private(path)
            if path.name in ('CONFIG.cbor','.store.lock'):continue
            if re.fullmatch(r'\.(?:submit|retire)-[A-Za-z0-9_-]+\.tmp',path.name):temp_bytes+=path.stat().st_size;continue
            if re.fullmatch('[a-f0-9]{64}\\.payload',path.name):payload_ids.add(bytes.fromhex(path.stem));continue
            if re.fullmatch('[a-f0-9]{64}\\.retire',path.name):retired_ids.add(bytes.fromhex(path.stem));continue
            if not re.fullmatch('[a-f0-9]{64}\\.stage',path.name):raise E('SUBMIT_LAYOUT')
            rows.append(self._read(bytes.fromhex(path.stem)))
        ids={d[5] for m,d in rows}
        if not set(self.seen)<=ids or not payload_ids<=ids or not retired_ids<=ids or not set(self.ret_seen)<=retired_ids:raise E('SUBMIT_CHANGED')
        for jid in retired_ids:self._record(jid)
        if temp_bytes>2*c.MAX_JOURNAL or len(rows)>self.config[4] or self._reserved(rows)>self.config[5]:raise E('SUBMIT_CAPACITY')
        return rows

    def diagnostics(self):
        rows=self.audit();retired=[self._record(d[5])[0] for m,d in rows if self.retirement_path(d[5]).exists()]
        return {'records':len(rows),'reserved_payload_bytes':self._reserved(rows),'maximum_records':self.config[4],
                'maximum_payload_bytes':self.config[5],'tombstones':sum(x[8]=='TOMBSTONED' for x in retired),
                'record_reclamation':False,'job_cancellation':False,'physical_disk_quota':False,'product_qualified':False}

    def _matching(self,raw):
        d=s.check_descriptor(self.p,raw)
        if self.retirement_path(d[5]).exists():raise E('SUBMIT_RETIRED')
        return super()._matching(raw)

    def begin(self,raw):
        with self.operation():
            d=s.check_descriptor(self.p,raw)
            if self.retirement_path(d[5]).exists():raise E('SUBMIT_RETIRED')
            d=self._descriptor(raw)
            if self._path(d[5]).exists():
                m,_=self._matching(raw);return self._view(m,d)
            self._current(d)
            rows=[self._read(bytes.fromhex(path.stem)) for path in self.root.glob('*.stage')]
            if len(rows)>=self.config[4] or self._reserved(rows)+d[7]>self.config[5]:raise E('SUBMIT_CAPACITY')
            jobs=self.jobs.journal.audit()
            if len(jobs)>=self.jobs.journal.config[4] and not self.jobs.journal.path(d[5]).exists():raise E('JOB_CAPACITY')
            m={0:1,1:s.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:raw,5:0,6:c.sha(b''),7:'RECEIVING',8:0,9:None}
            self._persist(m,'begin');return self._view(m,d)

    def proposal(self,descriptor):
        self.audit();d=s.check_descriptor(self.p,descriptor);m,_=self._read(d[5])
        if m[4]!=descriptor:raise E('RETIRE_TARGET')
        existing=self.retirement_path(d[5]).exists()
        b=self._record(d[5])[0] if existing else None
        return {'keeper':self.k.public,'store':self.host.gateway.store_id,'job_id':d[5],
                'descriptor_hash':c.sha(descriptor),'stage_hash':c.sha(self._source(d[5])),
                'target':b[6] if b else self._snapshot_payload(d),'previous':c.sha(b[7][-1]) if b else None}

    def _authorized(self,request,*,current=True):
        a=c.check_request(self.p,request)
        if current and self.ctl.policy()!=(a[8],a[9]):raise E('STALE_CONTROLLER')
        if (a[2],a[3])!=(self.k.public,self.host.gateway.store_id):raise E('RETIRE_TARGET')
        m,d=self._read(a[4])
        if a[10]!=d[4]:raise E('RETIRE_ORIGIN')
        if (a[5],a[6])!=(c.sha(m[4]),c.sha(self._source(a[4]))):raise E('RETIRE_TARGET')
        return a,m,d

    def _persist_retirement(self,b,label):
        raw=c.pack_record(self.p,self.k._seed,b)
        leftovers=list(self.root.glob('.retire-*.tmp'))
        for path in leftovers:private(path)
        if sum(p.stat().st_size for p in leftovers)+len(raw)>2*c.MAX_JOURNAL:raise E('RETIRE_CAPACITY')
        fd,name=tempfile.mkstemp(prefix='.retire-',suffix='.tmp',dir=self.root);tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();self.emit(label+'.before_fsync');os.fsync(f.fileno())
            self.emit(label+'.before_replace');path=self.retirement_path(b[4]);safe(path)
            if path.exists():private(path)
            os.replace(tmp,path);self.emit(label+'.after_replace');sync_dir(self.root);self.emit(label+'.after_sync')
            self.ret_seen[b[4]]=c.sha(raw)
        except BaseException:
            self.poison=True;raise E('RETIRE_JOURNAL_UNCERTAIN') from None
        finally:
            if tmp.exists():
                try:tmp.unlink()
                except OSError:pass

    def _status(self,b):
        return {'job_id':b[4].hex(),'state':b[8],'reservation_released_bytes':s.check_descriptor(self.p,s.split(b[5],s.MAX_RECORD)[0][4])[7] if b[8]=='TOMBSTONED' else 0,
                'removed_payload_bytes':b[6][1] if b[8]=='TOMBSTONED' else 0,'approvals':len(b[7]),
                'registered_job_digest':b[9].hex() if b[9] else None,'job_cancelled':False,'records_reclaimed':False,
                'secure_erase':False,'physical_disk_quota':False,'product_qualified':False}

    def retirement_status(self,jid):
        self.audit();return self._status(self._record(jid)[0])

    def reconcile_registration(self,request):
        """Explicit read/receipt update only; usable after controller rotation."""
        with self.operation():
            a,m,d=self._authorized(request)
            if self.retirement_path(d[5]).exists():raise E('SUBMIT_RETIRED')
            if a[12] is not None or a[7]!=self._snapshot_payload(d):raise E('RETIRE_TARGET')
            if m[7]!='INFLIGHT':raise E('RETIRE_NOT_INFLIGHT')
            fact=self._lookup(m,d)
            self._authorized(request)
            if fact is not None:return self._registered(m,d,fact)
            m[7]='RETRY_READY';m[8]+=1;self._persist(m,'retire_reconciled')
            return self._view(m,d)

    def rebind(self,request):
        with self.operation():
            a,m,d=self._authorized(request);b,_,_=self._record(d[5])
            if request==b[7][-1]:return self._status(b)
            last=c.check_request(self.p,b[7][-1])
            if a[12]!=c.sha(b[7][-1]) or a[7]!=b[6] or a[9]<=last[9]:raise E('RETIRE_REBIND')
            if len(b[7])>=c.MAX_APPROVALS:raise E('RETIRE_CAPACITY')
            b[7].append(request);self._persist_retirement(b,'retire_rebind');return self._status(b)

    def retire(self,request):
        with self.operation():
            a,m,d=self._authorized(request);jid=d[5]
            if self.retirement_path(jid).exists():
                b,_,_=self._record(jid)
                if request!=b[7][-1]:raise E('RETIRE_CONFLICT')
            else:
                if a[12] is not None or a[7]!=self._snapshot_payload(d):raise E('RETIRE_TARGET')
                if m[7]=='INFLIGHT':raise E('RETIRE_RECONCILE_REQUIRED')
                self._bound_job(m,d,m[9])
                b={0:1,1:c.PROFILE,2:self.k.public,3:self.host.gateway.store_id,4:jid,5:self._source(jid),
                   6:a[7],7:[request],8:'INTENT',9:m[9]}
                self._persist_retirement(b,'retire_intent')
            if b[8]=='TOMBSTONED':return self._status(b)
            if b[8]=='INTENT':
                self.emit('retire.before_unlink');self._authorized(request);self._record(jid)
                path=self.payload_path(jid)
                try:
                    if path.exists():path.unlink()
                    self.emit('retire.after_unlink');sync_dir(self.root);self.emit('retire.after_payload_sync')
                except BaseException:
                    self.poison=True;raise E('RETIRE_OUTCOME_UNKNOWN') from None
                self._authorized(request);self._record(jid)
                b[8]='PAYLOAD_REMOVED';self._persist_retirement(b,'retire_removed')
            self.emit('retire.before_release');self._authorized(request);self._record(jid)
            b[8]='TOMBSTONED';self._persist_retirement(b,'retire_tombstone')
            return self._status(b)

    def pin(self):
        rows=self.audit();entries=[]
        for m,d in sorted(rows,key=lambda r:r[1][5]):
            b=self._record(d[5])[0] if self.retirement_path(d[5]).exists() else None
            entries.append([d[5],c.sha(m[4]),m[8],c.sha(self._source(d[5])),
                            c.PHASES.index(b[8])+1 if b else 0,[c.sha(a) for a in b[7]] if b else []])
        return {0:c.PROFILE,1:self.k.public,2:self.host.gateway.store_id,3:c.sha(c.dump(self.config)),4:entries}

    def verify_pin(self,pin):
        try:
            now=self.pin();c.keys(pin,range(5))
            if c.dump([pin[i] for i in range(4)])!=c.dump([now[i] for i in range(4)]):raise ValueError()
            if type(pin[4]) is not list or len(pin[4])>s.MAX_RECORDS:raise ValueError()
            current={r[0]:r for r in now[4]};seen=[]
            for r in pin[4]:
                if type(r) is not list or len(r)!=6:raise ValueError()
                for i in (0,1,3):c.fixed(r[i])
                c.integer(r[2],0,2**53-1);c.integer(r[4],0,3)
                if type(r[5]) is not list or len(r[5])>c.MAX_APPROVALS:raise ValueError()
                for a in r[5]:c.fixed(a)
                if bool(r[5])!=(r[4]>0):raise ValueError()
                n=current[r[0]];seen.append(r[0])
                if n[1]!=r[1] or n[2]<r[2] or (n[2]==r[2] and n[3]!=r[3]) or n[4]<r[4] or n[5][:len(r[5])]!=r[5]:raise ValueError()
            if seen!=sorted(set(seen)):raise ValueError()
        except Exception:raise E('RETIRE_PIN') from None
        return True
