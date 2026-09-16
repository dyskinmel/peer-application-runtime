"""Bounded private upload journal, sharing the Keeper's cooperative owner thread.

This is a separate journal, not a two-database atomicity claim: destination commit
comes first, then the committed stage marker, then staging unlink. Repetition of
reserve/put is checked by the existing idempotent Keeper contract. Unacknowledged
file tails are truncated; acknowledged-prefix loss is never silently repaired.
Only this private staging directory is modified. No lease expiry or automatic GC.
"""
from pathlib import Path
import hashlib,os,stat,tempfile,threading
from par_store.fs import safe,regular,sync_dir,WriterLock
from par_recovery.transfer import read_file,mkdir
from par_recovery.contract import index_id,object_id,MAX_INDEX,MAX_OBJECT
from par_keeper.contract import (verify_capability,authority_body,dump as kd,split,
    pin_from,reserve_payload,put_payload,verify_call)
from . import protocol as p
E=p.E
MAX_RECORDS=1024;MAX_BYTES=16*1024*1024;META_LIMIT=2*p.MAX_REQUEST

def sha(b):return hashlib.sha256(b).digest()

def private(path,directory=False):
    safe(path);info=path.lstat()
    kind=stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid!=os.geteuid()
            or stat.S_IMODE(info.st_mode)!=(0o700 if directory else 0o600)
            or (not directory and info.st_nlink!=1)):
        raise E('STAGING_PERMISSIONS')

class Spool:
    def __init__(self,keeper,root,*,max_bytes=MAX_BYTES,max_records=MAX_RECORDS,observer=None):
        self.keeper=keeper;self.provider=keeper.provider;self.root=safe(Path(root));self.observer=observer
        self.closed=True;self.poison=False;self.lock=None;self.busy=False;self.thread=threading.get_ident()
        p.integer(max_bytes,1,MAX_BYTES);p.integer(max_records,1,MAX_RECORDS)
        if keeper._thread!=self.thread or keeper._closed:raise E('OWNER_REQUIRED')
        self.limits={0:1,1:keeper.public,2:max_bytes,3:max_records}
        try:
            mkdir(self.root);private(self.root,True);self.lock=WriterLock(self.root)
            cfg=self.root/'LIMITS.cbor'
            if cfg.exists():
                if p.load(read_file(cfg,4096),4096)!=self.limits:raise E('STAGING_SETTINGS')
            else:
                if any(f.name!='.store.lock' for f in self.root.iterdir()):raise E('STAGING_CORRUPT')
                self._atomic(cfg,self.limits,'init')
            self.closed=False;self._recover()
        except BaseException:self.close();raise
    def close(self):
        if self.lock is not None:self.lock.close();self.lock=None
        self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def _enter(self):
        if self.closed or self.keeper._closed:raise E('CLOSED')
        if self.poison:raise E('RECOVERY_REQUIRED')
        private(self.root,True)
        if self.busy or self.thread!=threading.get_ident():raise E('OWNER_REQUIRED')
    def _emit(self,event):
        if self.observer:self.observer(event)
    def _path(self,token,ext):
        p.fixed(token);return safe(self.root/(token.hex()+ext))
    def _atomic(self,path,value,label):
        raw=p.dump(value,META_LIMIT);fd,name=tempfile.mkstemp(dir=self.root,prefix='.upload-',suffix='.tmp');tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            self._emit(label+'.before_meta');safe(path);os.replace(tmp,path);self._emit(label+'.after_replace')
            sync_dir(self.root);self._emit(label+'.after_meta')
        except BaseException:
            self.poison=True;raise
        finally:
            if tmp.exists():tmp.unlink()
    def _meta(self,token,recover=False):
        path=self._path(token,'.cbor')
        if not path.exists():raise E('STAGE_UNKNOWN')
        private(path);m=p.load(read_file(path,META_LIMIT),META_LIMIT);p.keys(m,range(8))
        p.integer(m[0],1,1);p.fixed(m[1]);p.fixed(m[4])
        b=p.check_command(self.provider,m[2])
        if b[2]!='begin' or p.token_for(self.provider,m[2])!=token or m[1]!=token:raise E('STAGING_CORRUPT')
        total=b[7][2];p.integer(m[3],0,total)
        if m[5] not in ('active','committed'):raise E('STAGING_CORRUPT')
        if m[5]=='active':
            if m[6] is not None or m[7] is not None:raise E('STAGING_CORRUPT')
        else:
            c=p.check_command(self.provider,m[6]);self._same(c,b,token)
            if c[2]!=('reserve' if b[7][0]=='index' else 'put') or m[3]!=total:raise E('STAGING_CORRUPT')
            p.fixed(m[7])
            if m[4]!=b[7][3] or (b[7][0]=='object' and m[7]!=b[7][1]):raise E('STAGING_CORRUPT')
        part=self._path(token,'.part')
        if m[5]=='committed' and not part.exists():return m,b
        try:
            regular(part);private(part)
            if part.stat().st_nlink!=1:raise E('STAGING_CORRUPT')
            size=part.stat().st_size
            if size<m[3] or size>total:raise E('STAGING_CORRUPT')
            with part.open('rb') as f:prefix=f.read(m[3])
            if sha(prefix)!=m[4]:raise E('STAGING_CORRUPT')
            if size>m[3]:
                if not recover:raise E('RECOVERY_REQUIRED')
                fd=os.open(part,os.O_WRONLY|os.O_NOFOLLOW)
                try:os.ftruncate(fd,m[3]);os.fsync(fd)
                finally:os.close(fd)
        except E:raise
        except Exception:raise E('STAGING_CORRUPT') from None
        return m,b
    def _records(self):return [self._meta(bytes.fromhex(f.stem)) for f in self.root.glob('*.cbor') if f.name!='LIMITS.cbor']
    def _recover(self):
        import re
        entries=list(self.root.iterdir());tokens=[];parts=[];temps=[]
        for f in entries:
            safe(f);regular(f);private(f)
            if f.stat().st_nlink!=1:raise E('STAGING_CORRUPT')
            if f.name in ('LIMITS.cbor','.store.lock'):continue
            if re.fullmatch('[0-9a-f]{64}\\.cbor',f.name):tokens.append(bytes.fromhex(f.stem))
            elif re.fullmatch('[0-9a-f]{64}\\.part',f.name):parts.append(f)
            elif re.fullmatch(r'\.upload-[a-zA-Z0-9_-]+\.tmp',f.name):temps.append(f)
            else:raise E('STAGING_CORRUPT')
        if len(tokens)>self.limits[3]:raise E('STAGING_CORRUPT')
        total=0
        for token in tokens:
            m,b=self._meta(token,True)
            if m[5]=='committed':self._retire(token)
            else:total+=b[7][2]
        if total>self.limits[2]:raise E('STAGING_CORRUPT')
        # These files could never have received a durable acknowledgement.
        for f in parts:
            if bytes.fromhex(f.stem) not in tokens:f.unlink()
        for f in temps:f.unlink()
        sync_dir(self.root)
    def _same(self,c,b,token):
        if (c[4],c[6])!=(b[4],b[6]):raise E('STAGE_SCOPE')
        target=c[7][0] if c[2] in ('chunk','reserve') else c[7]
        if target!=token:raise E('STAGE_SCOPE')
    def _scope(self,c,b=None):
        k=self.keeper
        with k._operation():
            cap=verify_capability(k.provider,k.authority,k.public,c[4])
            if k.connection.execute('SELECT authority FROM metadata').fetchone()[0]!=kd(authority_body(k.authority)):raise E('STALE_AUTHORITY')
            base=b or c;action=c[2]
            kind=base[7][0] if base[2]=='begin' else None
            needed=('reserve' if kind=='index' else 'put') if action in ('begin','chunk','progress') else action
            if needed not in cap[6]:raise E('METHOD_DENIED')
            if base[6] is not None:
                row=k._lease(base[6]);k._serving(row)
                if row['owner']!=cap[4] or k._pin(row).index_id!=cap[5]:raise E('STAGE_SCOPE')
                if kind=='object':
                    oid,n,s=base[7][1:]
                    k._authorized(base[4],base[5],'put',base[6],[oid,n,s])
                    ds={d[0]:(d[1],d[2]) for d in k._info(row)[0]}
                    if oid not in ds or ds[oid][1]!=n:raise E('OBJECT_SCOPE')
                if action=='seal':k._authorized(c[4],c[5],'seal',c[6])
            return kd(authority_body(k.authority))
    def _progress(self,m,b):
        return p.progress_shape({0:m[1],1:m[3],2:b[7][2],3:m[4],4:m[5]=='committed',5:False})
    def _begin(self,c,raw):
        self._scope(c);token=p.token_for(self.provider,raw);path=self._path(token,'.cbor')
        if path.exists():
            m,b=self._meta(token)
            if m[2]!=raw:raise E('OPERATION_CONFLICT')
            return self._progress(m,b)
        if c[6] is not None and self.keeper._lease(c[6])['state']!='reserved':raise E('NOT_UPLOADING')
        records=self._records()
        if len(records)>=self.limits[3] or sum(b[7][2] for m,b in records if m[5]=='active')+c[7][2]>self.limits[2]:raise E('STAGING_CAPACITY')
        part=self._path(token,'.part');self._emit('begin.before_part')
        fd=os.open(part,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
        self._emit('begin.after_part')
        m={0:1,1:token,2:raw,3:0,4:sha(b''),5:'active',6:None,7:None}
        self._scope(c);self._atomic(path,m,'begin');return self._progress(m,c)
    def _chunk(self,c,m,b):
        token,offset,data=c[7];self._same(c,b,token);self._scope(c,b)
        if offset+len(data)>b[7][2]:raise E('CHUNK_RANGE')
        if m[5]!='active':raise E('STAGE_COMMITTED')
        part=self._path(token,'.part')
        if offset<m[3]:
            if offset+len(data)>m[3]:raise E('CHUNK_OFFSET')
            with part.open('rb') as f:f.seek(offset);old=f.read(len(data))
            if old!=data:raise E('CHUNK_CONFLICT')
            return self._progress(m,b)
        if offset!=m[3]:raise E('CHUNK_OFFSET')
        fd=os.open(part,os.O_RDWR|os.O_NOFOLLOW)
        with os.fdopen(fd,'r+b') as f:
            f.seek(offset);f.write(data);f.flush();self._emit('chunk.after_write');os.fsync(f.fileno());self._emit('chunk.after_fsync')
        m[3]=offset+len(data);m[4]=sha(read_file(part,max(MAX_INDEX,MAX_OBJECT)))
        self._scope(c,b);self._atomic(self._path(token,'.cbor'),m,'chunk');return self._progress(m,b)
    def _raw(self,m,b):
        if m[3]!=b[7][2]:raise E('STAGE_INCOMPLETE')
        raw=read_file(self._path(m[1],'.part'),max(MAX_INDEX,MAX_OBJECT))
        if len(raw)!=b[7][2] or sha(raw)!=b[7][3]:raise E('OBJECT_HASH')
        if b[7][0]=='index':
            if index_id(raw)!=b[7][1]:raise E('OBJECT_HASH')
        else:
            row=self.keeper._lease(b[6]);ds={d[0]:d[1] for d in self.keeper._info(row)[0]}
            if object_id(ds[b[7][1]],raw)!=b[7][1]:raise E('OBJECT_HASH')
        return raw
    def _retire(self,token):
        path=self._path(token,'.part')
        self._emit('retire.before_unlink')
        if path.exists():regular(path);path.unlink()
        self._emit('retire.after_unlink');sync_dir(self.root);self._emit('retire.after_sync')
    def _finalize(self,c,rawcmd,m,b):
        self._same(c,b,m[1]);self._scope(c,b);k=self.keeper
        if c[2]!=('reserve' if b[7][0]=='index' else 'put'):raise E('STAGE_SCOPE')
        if c[2]=='put' and c[5]!=b[5]:raise E('OPERATION_CONFLICT')
        if m[5]=='committed':
            if m[6]!=rawcmd:raise E('OPERATION_CONFLICT')
            if c[2]=='reserve':
                row=k._lease(m[7]);pin=pin_from(c[7][1]);result=k.reserve(row['index_raw'],pin,c[7][2],c[4],c[5])
            else:
                payload=k.object_path(c[6],m[7]);data=read_file(payload,MAX_OBJECT)
                k.put(c[6],m[7],data,c[4],c[5]);result=m[7]
            if result!=m[7]:raise E('STAGING_CORRUPT')
            self._retire(m[1]);return result
        data=self._raw(m,b);self._emit('finalize.before_keeper')
        if c[2]=='reserve':result=k.reserve(data,pin_from(c[7][1]),c[7][2],c[4],c[5])
        else:k.put(c[6],b[7][1],data,c[4],c[5]);result=b[7][1]
        self._emit('finalize.after_keeper');self._scope(c,b)
        m[5]='committed';m[6]=rawcmd;m[7]=result
        self._atomic(self._path(m[1],'.cbor'),m,'finalize');self._retire(m[1]);return result
    def execute(self,raw):
        self._enter();c=p.check_command(self.provider,raw);self.busy=True
        try:
            if c[2]=='begin':return self._begin(c,raw)
            if c[2]=='seal':
                self._scope(c);return self.keeper.seal(c[6],c[4],c[5])
            token=c[7][0] if c[2] in ('chunk','reserve') else c[7]
            m,b=self._meta(token);self._same(c,b,token);self._scope(c,b)
            if c[2]=='chunk':return self._chunk(c,m,b)
            if c[2]=='progress':return self._progress(m,b)
            return self._finalize(c,raw,m,b)
        except OSError:
            self.poison=True;raise E('OUTCOME_UNKNOWN') from None
        finally:self.busy=False
    def stamp(self,raw):
        self._enter();c=p.check_command(self.provider,raw)
        if c[2] in ('chunk','progress','reserve','put'):
            token=c[7][0] if c[2] in ('chunk','reserve') else c[7]
            m,b=self._meta(token);self._same(c,b,token);a=self._scope(c,b)
        else:a=self._scope(c)
        if c[6] is None:return a
        row=self.keeper._lease(c[6]);return a,row['state'],row['generation']
    def diagnostics(self):
        self._enter();records=self._records()
        return {'records':len(records),'reserved_bytes':sum(b[7][2] for m,b in records if m[5]=='active'),
            'max_bytes':self.limits[2],'max_records':self.limits[3],'automatic_gc':False,'product_qualified':False}
