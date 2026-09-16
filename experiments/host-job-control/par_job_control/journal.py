"""Bounded durable control intent ledger, separate from job effect journals.

INFLIGHT is written before dispatch. Recovery never replays it. An ACCEPTED result
only acknowledges the control request, never job completion. Private local files,
cooperating owner, not a hostile same-UID sandbox or an external rollback anchor.
"""
import os,re,tempfile,threading
from pathlib import Path
from par_store.fs import safe,WriterLock,sync_dir
from par_recovery.transfer import mkdir,read_file
from par_keeper_upload.spool import private
from . import protocol as c
E=c.E
LIMIT=8192
MAX_OPERATIONS=128
class Journal:
    def __init__(self,host,root,controller,revision,*,expected_pin=None,observer=None,max_operations=MAX_OPERATIONS):
        c.fixed(controller);c.integer(revision,1,2**53-1);c.integer(max_operations,1,MAX_OPERATIONS)
        self.h=host;self.p=host.provider;self.k=host.keeper;self.store=host.gateway.store_id
        self.root=safe(Path(root));self.owner=(os.getpid(),threading.get_ident());self.lock=None;self.closed=True;self.poison=False
        self.observer=observer;self.seen={};self.policy_raw=None;self.max_operations=max_operations
        for other in (host.keeper.root,host.gateway.root,host.jobs.journal.root):
            other=safe(Path(other))
            if self.root==other or self.root in other.parents or other in self.root.parents:raise E('CONTROL_PATH')
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root)
            self.closed=False;path=self.root/'POLICY.cbor'
            if path.exists():self.policy_raw=read_file(path,LIMIT)
            else:
                if any(p.name!='.store.lock' for p in self.root.iterdir()):raise E('CONTROL_LAYOUT')
                self._save_policy([[revision,controller]],'initialize')
            b=self.policy()
            if b[5][-1]!=[revision,controller] or b[4]!=max_operations:raise E('CONTROL_POLICY')
            self.audit()
            if expected_pin is not None:self.verify_pin(expected_pin)
        except BaseException:self.close();raise
    def guard(self):
        if self.owner!=(os.getpid(),threading.get_ident()):raise E('CONTROL_OWNER')
        if self.closed:raise E('CLOSED')
        if self.poison:raise E('CONTROL_JOURNAL_UNCERTAIN')
        if self.h.closed or self.p is not self.h.provider:raise E('CONTROL_OWNER')
        private(self.root,True)
    def emit(self,name):
        if self.observer:self.observer('control.'+name)
    def atomic(self,path,raw,label):
        self.guard()
        if len(raw)>LIMIT:raise E('CONTROL_CAPACITY')
        leftovers=list(self.root.glob('.ctl-*.tmp'))
        if sum(p.stat().st_size for p in leftovers)+len(raw)>2*LIMIT:raise E('CONTROL_CAPACITY')
        fd,name=tempfile.mkstemp(prefix='.ctl-',suffix='.tmp',dir=self.root);temp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();self.emit(label+'.before_fsync');os.fsync(f.fileno())
            self.emit(label+'.before_replace');safe(path)
            if path.exists():private(path)
            os.replace(temp,path);self.emit(label+'.after_replace');sync_dir(self.root);self.emit(label+'.after_sync')
        except BaseException:
            self.poison=True;raise E('CONTROL_JOURNAL_UNCERTAIN') from None
        finally:
            if temp.exists():
                try:temp.unlink()
                except OSError:pass
    def _save_policy(self,entries,label):
        b={0:1,1:c.PROFILE,2:self.k.public,3:self.store,4:self.max_operations,5:entries}
        raw=c._sign(self.p,self.k._seed,'policy',b,LIMIT)
        self.atomic(self.root/'POLICY.cbor',raw,label);self.policy_raw=raw
    def policy(self):
        self.guard();path=self.root/'POLICY.cbor';private(path);raw=read_file(path,LIMIT)
        if self.policy_raw!=raw:raise E('CONTROL_POLICY_CHANGED')
        b,o=c._split(raw,LIMIT);c.keys(b,range(6));c._version(b);c._verify(self.p,self.k.public,o,'policy')
        if (b[2],b[3],b[4])!=(self.k.public,self.store,self.max_operations):raise E('CONTROL_POLICY')
        c.integer(b[4],1,MAX_OPERATIONS)
        if type(b[5]) is not list or not 1<=len(b[5])<=32:raise E('CONTROL_POLICY')
        rev=0
        for e in b[5]:
            if type(e) is not list or len(e)!=2:raise E('CONTROL_POLICY')
            c.integer(e[0],rev+1,2**53-1)
            if e[1] is not None:c.fixed(e[1])
            rev=e[0]
        return b
    def rotate(self,public,revision):
        self.audit();b=self.policy();c.integer(revision,b[5][-1][0]+1,2**53-1)
        if public is not None:c.fixed(public)
        if len(b[5])>=32:raise E('CONTROL_CAPACITY')
        self._save_policy(b[5]+[[revision,public]],'rotate')
    def path(self,oid):c.fixed(oid);return self.root/(oid.hex()+'.op')
    def read(self,oid):
        self.guard();path=self.path(oid);private(path);raw=read_file(path,LIMIT)
        if oid in self.seen and self.seen[oid]!=c.digest(raw):raise E('CONTROL_JOURNAL_CHANGED')
        b,o=c._split(raw,LIMIT);c.keys(b,range(7));c._version(b);c._verify(self.p,self.k.public,o,'record')
        ib,i=c.inspect_intent(self.p,b[4])
        if (b[2],b[3],ib[2],ib[3],i.operation_id)!=(self.k.public,self.store,self.k.public,self.store,oid):raise E('CONTROL_RECORD')
        if i.action not in c.MUTATIONS or b[5] not in ('INFLIGHT','ACCEPTED','OUTCOME_UNKNOWN') or b[6] is not None:raise E('CONTROL_RECORD')
        if [i.revision,i.controller] not in self.policy()[5]:raise E('CONTROL_RECORD')
        self.seen[oid]=c.digest(raw);return b,raw
    def audit(self):
        self.policy();found=set();temps=0
        for p in self.root.iterdir():
            private(p)
            if p.name in ('POLICY.cbor','.store.lock'):continue
            if re.fullmatch(r'\.ctl-[a-zA-Z0-9_-]+\.tmp',p.name):
                temps+=p.stat().st_size;continue
            if not re.fullmatch('[a-f0-9]{64}\\.op',p.name):raise E('CONTROL_LAYOUT')
            oid=bytes.fromhex(p.stem);found.add(oid);self.read(oid)
        if not set(self.seen)<=found:raise E('CONTROL_JOURNAL_CHANGED')
        if len(found)>self.max_operations or temps>2*LIMIT:raise E('CONTROL_CAPACITY')
        return found
    def lookup(self,i):
        self.audit()
        if not self.path(i.operation_id).exists():return None
        b,raw=self.read(i.operation_id)
        if b[4]!=i.raw:raise E('CONTROL_CONFLICT')
        return 'OUTCOME_UNKNOWN' if b[5]=='INFLIGHT' else b[5]
    def start(self,i):
        ids=self.audit()
        if i.operation_id in ids:raise E('CONTROL_CONFLICT')
        if len(ids)>=self.max_operations:raise E('CONTROL_CAPACITY')
        b={0:1,1:c.PROFILE,2:self.k.public,3:self.store,4:i.raw,5:'INFLIGHT',6:None}
        self.persist(b,'inflight')
    def finish(self,i,state):
        b,_=self.read(i.operation_id)
        if b[4]!=i.raw or b[5]!='INFLIGHT' or state not in ('ACCEPTED','OUTCOME_UNKNOWN'):raise E('CONTROL_RECORD')
        b[5]=state;self.persist(b,'result')
    def persist(self,b,label):
        _,i=c.inspect_intent(self.p,b[4]);raw=c._sign(self.p,self.k._seed,'record',b,LIMIT)
        self.atomic(self.path(i.operation_id),raw,label);self.seen[i.operation_id]=c.digest(raw)
    def pin(self):
        ids=self.audit();items=[]
        for oid in sorted(ids):
            b,raw=self.read(oid);items.append([oid,c.digest(b[4]),None if b[5]=='INFLIGHT' else c.digest(raw)])
        return {0:c.PROFILE,1:self.k.public,2:self.store,3:self.policy()[5],4:items}
    def verify_pin(self,pin):
        try:
            self.audit();c.keys(pin,range(5))
            if (pin[0],pin[1],pin[2])!=(c.PROFILE,self.k.public,self.store):raise ValueError()
            policies=self.policy()[5]
            c.fixed(pin[1]);c.fixed(pin[2])
            if type(pin[3]) is not list or not pin[3] or c.dump(policies[:len(pin[3])],LIMIT)!=c.dump(pin[3],LIMIT):raise ValueError()
            if type(pin[4]) is not list or len(pin[4])>self.max_operations:raise ValueError()
            ids=[]
            for item in pin[4]:
                if type(item) is not list or len(item)!=3:raise ValueError()
                oid,intent,expected=item;c.fixed(oid);c.fixed(intent);ids.append(oid)
                b,raw=self.read(oid)
                if c.digest(b[4])!=intent:raise ValueError()
                if expected is not None:
                    c.fixed(expected)
                    if c.digest(raw)!=expected:raise ValueError()
            if ids!=sorted(set(ids)):raise ValueError()
        except Exception:raise E('CONTROL_PIN') from None
        return True
    def close(self):
        if self.owner!=(os.getpid(),threading.get_ident()):raise E('CONTROL_OWNER')
        if self.lock is not None:self.lock.close();self.lock=None
        self.closed=True
