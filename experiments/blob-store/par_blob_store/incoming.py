"""Bounded POSIX spool for untrusted sealed bytes, independent of published Store.

Only file bytes followed by durable metadata acknowledgement advance the offset.
A crash may leave an unacknowledged tail; reopen truncates it. Acknowledged prefix
loss/corruption is fail-closed. No receipt, membership decision or GC of Store data.
"""
from __future__ import annotations
import json, os, re, secrets, tempfile, threading
from pathlib import Path
from par_store.fs import safe, regular, sync_dir, WriterLock
from par_store.model import BLOCK_MAX
from par_store.errors import StoreError
from par_crypto import objects
from par_wire.codec import decode
from .model import Attachment,verify_attachment,sha,MAX_BATCH_BYTES,BLOB_KIND
from .errors import BlobStoreError as E

TOKEN=re.compile(r'[0-9a-f]{32}')
KEYS={'version','id','typed_id','header','total','ack','prefix_sha256'}
def pairs(items):
    out={}
    for k,v in items:
        if k in out:raise ValueError('duplicate JSON key')
        out[k]=v
    return out

def json_read(p):
    regular(p)
    if p.stat().st_size>16384:raise E('TRANSFER_CORRUPT')
    try:return json.loads(p.read_text('utf-8'),object_pairs_hook=pairs)
    except (UnicodeError,ValueError):raise E('TRANSFER_CORRUPT') from None

class IncomingQueue:
    def __init__(self,root,lock,limits,observer=None):
        self.root=root;self._lock=lock;self.limits=limits;self.observer=observer
        self.closed=False;self._busy=False;self._poison=False;self._thread=threading.get_ident()
    def _notify(self,stage):
        if self.observer:self.observer(stage)
    def _enter(self):
        if self.closed:raise E('TRANSFER_CLOSED')
        if self._poison:raise E('TRANSFER_RECOVERY_REQUIRED')
        if self._busy or threading.get_ident()!=self._thread:raise E('REENTRANT_OPERATION')
    def close(self):
        if not self.closed:self._lock.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    @staticmethod
    def _limits(items,size):
        if type(items) is not int or not 1<=items<=32 or type(size) is not int or not 1<=size<=MAX_BATCH_BYTES:raise E('TRANSFER_INPUT')
        return {'version':1,'max_items':items,'max_bytes':size}
    @classmethod
    def create(cls,root,*,max_items=16,max_bytes=MAX_BATCH_BYTES,observer=None):
        limits=cls._limits(max_items,max_bytes);root=safe(Path(root))
        if root.exists() and list(root.iterdir()):raise E('TRANSFER_ROOT_NOT_EMPTY')
        root.mkdir(mode=0o700,parents=True,exist_ok=True);lock=WriterLock(root);self=cls(root,lock,limits,observer)
        try:self._write_json(root/'QUEUE.json',limits);sync_dir(root.parent);return self
        except BaseException:self.close();raise
    @classmethod
    def open(cls,root,*,observer=None):
        root=safe(Path(root))
        if not root.is_dir():raise E('TRANSFER_MISSING')
        lock=WriterLock(root)
        try:
            obj=json_read(root/'QUEUE.json')
            if type(obj) is not dict or set(obj)!={'version','max_items','max_bytes'} or type(obj['version']) is not int or obj['version']!=1:raise E('TRANSFER_CORRUPT')
            cls._limits(obj['max_items'],obj['max_bytes'])
            self=cls(root,lock,obj,observer);self._recover();return self
        except BaseException:lock.close();raise
    def _path(self,token,suffix):
        if type(token) is not str or TOKEN.fullmatch(token) is None:raise E('TRANSFER_INPUT')
        return safe(self.root/(token+suffix))
    def _write_json(self,target,obj,*,ack=False):
        data=(json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode()
        fd,name=tempfile.mkstemp(prefix='.meta-',suffix='.tmp',dir=self.root);tmp=Path(name);published=False
        try:
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            if ack:self._notify('incoming.before_ack_publish')
            safe(target);os.replace(tmp,target);published=True
            sync_dir(self.root)
            if ack:self._notify('incoming.after_ack_publish')
        except BaseException as exc:
            if published and not isinstance(exc,(KeyboardInterrupt,SystemExit)):raise E('TRANSFER_OUTCOME_UNKNOWN') from None
            raise
        finally:
            if tmp.exists():tmp.unlink()
    def _meta(self,token,*,recover=False):
        path=self._path(token,'.json')
        if not path.exists():raise E('TRANSFER_MISSING')
        m=json_read(path)
        try:
            if type(m) is not dict or set(m)!=KEYS or type(m['version']) is not int or m['version']!=1 or m['id']!=token:raise ValueError()
            if type(m['total']) is not int or not 1<=m['total']<=BLOCK_MAX or type(m['ack']) is not int or not 0<=m['ack']<=m['total']:raise ValueError()
            if any(type(m[k]) is not str for k in ('typed_id','header','prefix_sha256')):raise ValueError()
            if not re.fullmatch('[0-9a-f]{64}',m['typed_id']) or not re.fullmatch('[0-9a-f]{64}',m['prefix_sha256']):raise ValueError()
            hb=bytes.fromhex(m['header']);header=objects.parse('block-header',hb,4096)
            if objects.block_header(header)!=hb or header[4]!=BLOB_KIND:raise ValueError()
            p=self._path(token,'.part');regular(p);size=p.stat().st_size
            if size<m['ack'] or size>BLOCK_MAX:raise ValueError()
            with p.open('rb') as f:data=f.read(m['ack'])
            if sha(data).hex()!=m['prefix_sha256']:raise ValueError()
            if size>m['ack']:
                if not recover:raise E('TRANSFER_RECOVERY_REQUIRED')
                fd=os.open(p,os.O_WRONLY|os.O_NOFOLLOW)
                try:os.ftruncate(fd,m['ack']);os.fsync(fd)
                finally:os.close(fd)
            return m
        except E:raise
        except Exception:raise E('TRANSFER_CORRUPT') from None
    def _recover(self):
        metadata=[];parts=[];temps=[]
        for p in self.root.iterdir():
            safe(p);regular(p)
            if p.name in ('QUEUE.json','.store.lock'):continue
            if re.fullmatch(r'[0-9a-f]{32}\.json',p.name):metadata.append(p.stem)
            elif re.fullmatch(r'[0-9a-f]{32}\.part',p.name):parts.append(p)
            elif re.fullmatch(r'\.meta-[a-zA-Z0-9_-]+\.tmp',p.name):temps.append(p)
            else:raise E('TRANSFER_CORRUPT')
        if len(metadata)>self.limits['max_items']:raise E('TRANSFER_LIMIT')
        total=0
        for token in metadata:total+=self._meta(token,recover=True)['total']
        if total>self.limits['max_bytes']:raise E('TRANSFER_LIMIT')
        # Only this private spool's never-acknowledged files are discarded.
        for p in parts:
            if p.stem not in metadata:p.unlink()
        for p in temps:p.unlink()
        sync_dir(self.root)
    def begin(self,typed_id,header_bytes,total):
        self._enter()
        if type(typed_id) is not bytes or len(typed_id)!=32 or type(header_bytes) is not bytes:raise E('TRANSFER_INPUT')
        if type(total) is not int or not 1<=total<=BLOCK_MAX:raise E('TRANSFER_LIMIT')
        h=objects.parse('block-header',header_bytes,4096)
        if objects.block_header(h)!=header_bytes or h[4]!=BLOB_KIND:raise E('TRANSFER_INPUT')
        rows=[self._meta(p.stem) for p in self.root.glob('*.json') if p.name!='QUEUE.json']
        if len(rows)>=self.limits['max_items'] or sum(r['total'] for r in rows)+total>self.limits['max_bytes']:raise E('TRANSFER_LIMIT')
        token=secrets.token_hex(16);part=self._path(token,'.part');self._busy=True
        try:
            fd=os.open(part,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:os.fsync(fd)
            finally:os.close(fd)
            self._notify('incoming.after_part_create')
            self._write_json(self._path(token,'.json'),{'version':1,'id':token,'typed_id':typed_id.hex(),'header':header_bytes.hex(),'total':total,'ack':0,'prefix_sha256':sha(b'').hex()})
            self._notify('incoming.after_begin');return token
        except BaseException as exc:
            self._poison=True
            if isinstance(exc,StoreError):raise
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            raise E('TRANSFER_OUTCOME_UNKNOWN') from None
        finally:self._busy=False
    def append(self,token,offset,data):
        self._enter()
        if type(offset) is not int or offset<0 or type(data) is not bytes or not data:raise E('TRANSFER_INPUT')
        if len(data)>BLOCK_MAX:raise E('TRANSFER_LIMIT')
        m=self._meta(token);p=self._path(token,'.part')
        if offset+len(data)>m['total']:raise E('TRANSFER_LIMIT')
        if offset<m['ack']:
            if offset+len(data)>m['ack']:raise E('TRANSFER_OFFSET')
            with p.open('rb') as f:f.seek(offset);existing=f.read(len(data))
            if existing!=data:raise E('TRANSFER_CONFLICT')
            return m['ack']
        if offset!=m['ack']:raise E('TRANSFER_OFFSET')
        self._busy=True
        try:
            fd=os.open(p,os.O_RDWR|os.O_NOFOLLOW)
            with os.fdopen(fd,'r+b') as f:
                f.seek(offset);f.write(data);f.flush();self._notify('incoming.after_data_write');os.fsync(f.fileno());self._notify('incoming.after_data_fsync')
            raw=p.read_bytes();m['ack']=offset+len(data);m['prefix_sha256']=sha(raw).hex()
            self._write_json(self._path(token,'.json'),m,ack=True)
            return m['ack']
        except BaseException as exc:
            self._poison=True
            if isinstance(exc,StoreError):raise
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            raise E('TRANSFER_OUTCOME_UNKNOWN') from None
        finally:self._busy=False
    def status(self,token):
        self._enter();m=self._meta(token)
        return {'id':token,'acknowledged_bytes':m['ack'],'expected_bytes':m['total'],'bytes_complete':m['ack']==m['total'],'referenced':False,'receipt_issued':False}
    def finish(self,token,provider,epoch_secret,*,app,space,epoch):
        self._enter();m=self._meta(token)
        if m['ack']!=m['total']:raise E('TRANSFER_INCOMPLETE')
        a=Attachment(bytes.fromhex(m['typed_id']),bytes.fromhex(m['header']),self._path(token,'.part').read_bytes())
        verify_attachment(provider,epoch_secret,a,app=app,space=space,epoch=epoch)
        return a
    def discard(self,token):
        """Explicitly retire only this spool copy, never a Store/recovery root."""
        self._enter();self._meta(token);self._busy=True
        try:
            self._path(token,'.json').unlink();sync_dir(self.root)
            self._notify('incoming.after_retire')
            self._path(token,'.part').unlink();sync_dir(self.root)
            self._notify('incoming.after_discard')
        except BaseException as exc:
            self._poison=True
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            raise E('TRANSFER_OUTCOME_UNKNOWN') from None
        finally:self._busy=False
