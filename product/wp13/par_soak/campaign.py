"""Bounded, source-bound observation campaigns, not a product retry engine.

A completed round is immutable. Failure is terminal. A BEGIN without a RESULT is
ambiguous after a crash and cannot be replayed. Graceful boundary stops resume at
the next identity. The hash chain detects corruption, not same-user forgery or
rollback of both the files and all external pins. No input state is deleted.
"""
from __future__ import annotations
import fcntl,hashlib,json,os,re,stat,threading
from pathlib import Path

SCENARIOS=('observe','inquire','reject','cancel','timeout','close-failure','disconnect')
MAX_EVENT_BYTES=131072

def need(value,code):
    if not value:raise ValueError(code)

def pack(value):
    raw=json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    need(len(raw)<=MAX_EVENT_BYTES,'CAMPAIGN_BUDGET');return raw

def sha(value):return hashlib.sha256(pack(value)).hexdigest()

def config_value(binding,config):
    need(type(binding)is dict and set(binding)=={'source','environment'},'CAMPAIGN_BINDING')
    need(all(type(x)is str and re.fullmatch('[0-9a-f]{64}',x)for x in binding.values()),'CAMPAIGN_BINDING')
    need(type(config)is dict and set(config)=={'rounds','seed'},'CAMPAIGN_CONFIG')
    need(type(config['rounds'])is int and 1<=config['rounds']<=256,'CAMPAIGN_CONFIG')
    need(type(config['seed'])is int and 0<=config['seed']<2**32,'CAMPAIGN_CONFIG')
    return {'profile':'par-local-soak-0054','binding':dict(binding),'config':dict(config)}

class Campaign:
    @classmethod
    def create(cls,root,binding,config):
        manifest=config_value(binding,config);root=Path(root)
        root.mkdir(mode=0o700)  # create-only; never overwrite another campaign
        obj=cls._lock(root)
        try:
            obj._write('manifest.json',manifest);obj._manifest=manifest;obj._events=[];obj._reopened=False;return obj
        except BaseException:obj.close();raise

    @classmethod
    def open(cls,root,binding,config,*,pin=None):
        expected=config_value(binding,config);obj=cls._lock(Path(root))
        try:
            obj._manifest=obj._read('manifest.json');need(obj._manifest==expected,'CAMPAIGN_BINDING')
            names=set(p.name for p in obj.root.iterdir());need(names>={'lease','manifest.json'},'CAMPAIGN_CORRUPT')
            events=sorted(names-{'lease','manifest.json'});need(len(events)<=1024,'CAMPAIGN_BUDGET')
            need(events==[f'{i:06}.json'for i in range(1,len(events)+1)],'CAMPAIGN_CORRUPT')
            obj._events=[]
            for name in events:
                value=obj._read(name);need(type(value)is dict and set(value)=={'sequence','previous','kind','payload'},'CAMPAIGN_CORRUPT')
                need(value['sequence']==len(obj._events)+1 and value['previous']==obj.pin()['digest'],'CAMPAIGN_CORRUPT')
                obj._validate(value['kind'],value['payload'],replaying=True);obj._events.append(value)
            if pin is not None:
                need(type(pin)is dict and set(pin)=={'sequence','digest'}and type(pin['sequence'])is int,'CAMPAIGN_PIN')
                n=pin['sequence'];need(0<=n<=len(obj._events),'CAMPAIGN_PIN')
                need(pin['digest']==sha(obj._manifest if n==0 else obj._events[n-1]),'CAMPAIGN_PIN')
            obj._sync();obj._reopened=True;return obj
        except BaseException:obj.close();raise

    @classmethod
    def _lock(cls,root):
        obj=cls();obj.root=root.absolute();obj._fd=None;obj._poison=False;obj._identity=(os.getpid(),threading.get_ident())
        s=obj.root.lstat();need(stat.S_ISDIR(s.st_mode)and not stat.S_ISLNK(s.st_mode)and s.st_mode&0o777==0o700 and s.st_uid==os.getuid()and obj.root.resolve()==obj.root,'CAMPAIGN_UNSAFE')
        obj._dir_identity=(s.st_dev,s.st_ino)
        fd=os.open(obj.root/'lease',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            s=os.fstat(fd);need(stat.S_ISREG(s.st_mode)and s.st_mode&0o777==0o600 and s.st_nlink==1 and s.st_uid==os.getuid(),'CAMPAIGN_UNSAFE')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('CAMPAIGN_LOCKED')from None
            obj._fd=fd;return obj
        except BaseException:os.close(fd);raise

    def _check(self):
        need(self._fd is not None,'CAMPAIGN_CLOSED');need(not self._poison,'CAMPAIGN_POISONED')
        need(self._identity==(os.getpid(),threading.get_ident()),'CAMPAIGN_WRONG_OWNER')
        s=self.root.lstat();need((s.st_dev,s.st_ino)==self._dir_identity and s.st_mode&0o777==0o700,'CAMPAIGN_UNSAFE')

    def _sync(self):
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _read(self,name):
        try:fd=os.open(self.root/name,os.O_RDONLY|os.O_NOFOLLOW)
        except OSError as exc:raise ValueError('CAMPAIGN_UNSAFE')from exc
        try:
            st=os.fstat(fd);need(stat.S_ISREG(st.st_mode)and st.st_mode&0o777==0o600 and st.st_nlink==1 and st.st_uid==os.getuid(),'CAMPAIGN_UNSAFE')
            need(0<st.st_size<=MAX_EVENT_BYTES,'CAMPAIGN_CORRUPT');raw=b''
            while len(raw)<=st.st_size:
                part=os.read(fd,st.st_size+1-len(raw))
                if not part:break
                raw+=part
            try:
                value=json.loads(raw);need(pack(value)==raw,'CAMPAIGN_CORRUPT')
            except (ValueError,UnicodeError,RecursionError)as exc:raise ValueError('CAMPAIGN_CORRUPT')from exc
            need(len(raw)==st.st_size,'CAMPAIGN_CORRUPT');os.fsync(fd);return value
        finally:os.close(fd)

    def _write(self,name,value):
        raw=pack(value) # invalid input does not poison a healthy handle
        try:
            fd=os.open(self.root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                view=memoryview(raw)
                while view:
                    n=os.write(fd,view);need(n>0,'CAMPAIGN_WRITE');view=view[n:]
                os.fsync(fd)
            finally:os.close(fd)
            self._sync();need(self._read(name)==value,'CAMPAIGN_CORRUPT')
        except BaseException:self._poison=True;raise

    def _status(self):
        active=None;completed=0;failed=None;sealed=False
        for e in self._events:
            if e['kind']=='BEGIN':active=e['payload']['round'];sealed=False
            elif e['kind']=='RESULT':
                if e['payload']['status']=='FAIL':failed=e['payload']
                else:completed+=1
                active=None;sealed=False
            elif e['kind']=='ABORT':failed=e['payload'];sealed=False
            elif e['kind']=='SEAL':sealed=True
        total=self._manifest['config']['rounds']
        result=('FAIL'if failed is not None else 'INTERRUPTED'if active is not None else
                'UNSEALED'if completed and not sealed else 'PASS'if completed==total else 'PARTIAL')
        return {'result':result,'completed':completed,'total':total,'next_round':completed,'active':active,'first_failure':failed}

    def state(self):self._check();return self._status()
    def pin(self):
        self._check();return {'sequence':len(self._events),'digest':sha(self._events[-1]if self._events else self._manifest)}
    def records(self):self._check();return json.loads(json.dumps(self._events))
    def scenario(self,index):
        need(type(index)is int and 0<=index<self._manifest['config']['rounds'],'ROUND_ORDER')
        seed=self._manifest['config']['seed'];block=index//len(SCENARIOS)
        order=sorted(SCENARIOS,key=lambda s:hashlib.sha256(f'{seed}:{block}:{s}'.encode()).hexdigest())
        return order[index%len(SCENARIOS)]

    def _validate(self,kind,payload,*,replaying=False):
        def valid(v,c):need(v,'CAMPAIGN_CORRUPT'if replaying else c)
        s=self._status();valid(s['first_failure']is None,'CAMPAIGN_FAILED')
        valid(type(payload)is dict,'CAMPAIGN_CORRUPT')
        if kind=='ABORT':
            valid(set(payload)=={'reason'}and type(payload['reason'])is str and 0<len(payload['reason'])<=4096,'CAMPAIGN_STATUS');return
        if kind=='SEAL':
            valid(set(payload)=={'through','child_exit_codes'}and type(payload['through'])is int and payload['through']==s['completed']and s['active']is None and payload['child_exit_codes']==[0,0],'CAMPAIGN_FINALIZATION');return
        valid(type(payload.get('round'))is int,'ROUND_ORDER')
        if kind=='BEGIN':
            valid(s['active']is None,'CAMPAIGN_ACTIVE');valid(s['completed']<s['total'],'CAMPAIGN_COMPLETE')
            valid(set(payload)=={'round','scenario'}and payload['round']==s['next_round'],'ROUND_ORDER')
            valid(payload['scenario']==self.scenario(payload['round']),'ROUND_ORDER')
        else:
            valid(kind=='RESULT','CAMPAIGN_CORRUPT');valid(s['active']is not None,'CAMPAIGN_NO_ACTIVE')
            valid(payload['round']==s['active'],'ROUND_ORDER');valid(payload.get('status')in('PASS','FAIL'),'CAMPAIGN_STATUS')
            pack(payload)
    def _append(self,kind,payload):
        self._check();self._validate(kind,payload)
        # Canonical copy prevents subsequent caller mutation of cached evidence.
        e=json.loads(pack({'sequence':len(self._events)+1,'previous':self.pin()['digest'],'kind':kind,'payload':payload}))
        self._write(f'{e["sequence"]:06}.json',e);self._events.append(e)
    def begin(self,index):
        self._check();need(not self._reopened or self._status()['result']!='UNSEALED','CAMPAIGN_FINALIZATION_UNCONFIRMED');need(self._status()['completed']<self._manifest['config']['rounds'],'CAMPAIGN_COMPLETE')
        self._append('BEGIN',{'round':index,'scenario':self.scenario(index)});self._reopened=False
    def finish(self,index,result):
        need(type(result)is dict and result.get('round')==index,'ROUND_ORDER');self._append('RESULT',result)
    def seal(self):
        self._append('SEAL',{'through':self._status()['completed'],'child_exit_codes':[0,0]})
    def abort(self,reason):
        self._check()
        if self._status()['first_failure']is None:self._append('ABORT',{'reason':reason})
    def close(self):
        if self._fd is not None:os.close(self._fd);self._fd=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
