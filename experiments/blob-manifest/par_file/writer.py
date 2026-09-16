"""Plaintext file → durable sealed artifacts → existing authenticated Blob commit.

Staging is restartable; its acknowledgment is NOT document persistence. The
journal contains only encrypted records. Complete commits are recoverable from
BlobStore alone, without this journal. Input/commit memory is explicitly bounded.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib,hmac,os,stat
from par_blob_store import BlobWriter,Attachment,inspect_attachment
from par_crypto import objects
from par_crypto.primitives import domain,hashed
from par_wire.codec import encode,decode
from par_store.fs import safe
from par_store.errors import StoreError
from .errors import FileError as E
from . import manifest as M
from .journal import read_bounded,make_dir,publish,durable_existing,clean_unacknowledged

@dataclass(frozen=True)
class StagedFile:
    operation_id: bytes
    intent: bytes
    file_id: bytes
    manifest_id: bytes
    chunks: int
    size: int
    state: str='STAGED'

class FileWriter:
    def __init__(self,store,certificate,epoch_secret,signing_seed,local_secret,*,observer=None,random_source=None,max_jobs=16):
        if type(max_jobs) is not int or not 1<=max_jobs<=256:raise E('FILE_STAGE_BUDGET')
        self.store=store;self.blob=BlobWriter(store,certificate,epoch_secret,signing_seed,local_secret)
        self.crypto=self.blob.crypto;self.crypto.random_source=random_source
        self.p=store._provider;self.observer=observer;self.max_jobs=max_jobs;self._busy=False
    def _notify(self,name):
        if self.observer:
            try:self.observer(name)
            except Exception:raise E('FILE_INTERRUPTED') from None
    def _start(self,write=False):
        self.store._enter(write)
        if self._busy or getattr(self.store,'_file_generation_active',False):raise E('REENTRANT_OPERATION')
        self._busy=True;self.store._file_generation_active=True
    def _end(self):self._busy=False;self.store._file_generation_active=False
    def _subop(self,op):
        if type(op) is not bytes or len(op)!=16:raise E('FILE_INPUT_INVALID')
        v=hmac.digest(self.crypto._local_key('file-operation'),domain('file-local/stage-operation',[op]),'sha256')[:16]
        if v==op:raise E('FILE_INPUT_INVALID')
        return v
    def _directory(self,op,*,create=False):
        parent=safe(self.store._storage.root/'staging'/'files');root=safe(parent/self._subop(op).hex())
        if create:
            make_dir(parent)
            jobs=list(parent.iterdir())
            for p in jobs:
                safe(p)
                if not p.is_dir():raise E('FILE_ARTIFACT_INVALID')
            if not root.exists() and len(jobs)>=self.max_jobs:raise E('FILE_STAGE_BUDGET')
            make_dir(root)
        elif not root.is_dir():raise E('FILE_STAGE_MISSING')
        return root
    def _intent(self,record):
        body={k:record[k] for k in range(9)}
        return hmac.digest(self.crypto._local_key('file-intent-digest'),encode(body,max_bytes=32768),'sha256')
    def _record(self,op,h,payload,cache,size,digest,name,mime):
        base=self.crypto._input(op,h,payload,cache)
        fid=hashed('file-local/object',[h[0],h[1],h[2],h[3],h[5],op])
        r={0:1,1:op,2:objects.change_header(h),3:base,4:size,5:digest,6:name,7:mime,8:fid}
        r[9]=self._intent(r);return r
    def _issued(self,op,intent,key,nonce):
        row=self.store._storage.connection.execute('SELECT payload_digest FROM issued_nonces WHERE key_context=? AND nonce=?',(hashed('crypto-local/key-id',[key]),nonce)).fetchone()
        if row is None or row[0]!=intent:raise E('FILE_NONCE_RECORD_MISSING')
        r=self.store._storage.connection.execute('SELECT input_digest FROM local_operation_intents WHERE operation_id=?',(self._subop(op),)).fetchone()
        if r is None or r[0]!=intent:raise E('FILE_OPERATION_CONFLICT')
    def _read_record(self,op):
        root=self._directory(op);raw=read_bounded(root/'intent.cbor',65536)
        fid=None
        # Public local framing binds op/store; the file ID is encrypted in the record.
        try:
            plain=self.crypto._open_local('file-intent',self._subop(op),hashed('file-local/journal',[op]),raw)
            r=decode(plain,max_bytes=32768)
            if type(r) is not dict or set(r)!=set(range(10)) or any(type(k) is not int for k in r):raise ValueError()
            if type(r[0]) is not int or r[0]!=1 or r[1]!=op or self._intent(r)!=r[9]:raise ValueError()
            h=objects.parse('change-header',r[2],16384);objects.change_header(h)
            if r[8]!=hashed('file-local/object',[h[0],h[1],h[2],h[3],h[5],op]):raise ValueError()
            for k in (3,5,8,9):
                if type(r[k]) is not bytes or len(r[k])!=32:raise ValueError()
            if type(r[4]) is not int or not 0<=r[4]<=M.MAX_FILE_BYTES:raise ValueError()
            M.metadata(r[6],r[7]);objects._author(self.p,self.p.sign_public(self.crypto.signing_seed),h)
            outer=decode(raw);self._issued(op,r[9],self.crypto._local_key('file-intent'),outer[1])
            return root,r,h
        except E:raise
        except Exception:raise E('FILE_ARTIFACT_INVALID') from None
    def _header(self,r,h,i,length):return {0:h[0],1:h[1],2:h[2],3:r[8],4:3,5:i,6:h[15],7:length}
    def _read_chunk(self,path,r,header):
        raw=read_bounded(path);outer=decode(raw,max_bytes=270336)
        self._issued(r[1],r[9],objects._key(self.crypto.epoch_secret,header,True),outer[1])
        plain=objects.open_block(self.p,self.crypto.epoch_secret,header,raw)
        return Attachment(objects.block_id(raw),objects.block_header(header),raw),plain
    def _seal(self,r,header,plain,prefix,path):
        key=objects._key(self.crypto.epoch_secret,header,True)
        _,nonce=self.crypto._reserve(self._subop(r[1]),r[9],key);self._notify(prefix+'.reserved')
        raw=objects.seal_block(self.p,self.crypto.epoch_secret,header,plain,nonce);self._notify(prefix+'.sealed')
        publish(path,raw,self._notify,prefix)
        return Attachment(objects.block_id(raw),objects.block_header(header),raw)
    def _all(self,op):
        root,r,h=self._read_record(op)
        if not (root/'manifest.cbor').exists():raise E('FILE_INCOMPLETE')
        raw=read_bounded(root/'manifest.cbor');o=objects.parse('sealed-block',raw,270336)
        a=Attachment(objects.block_id(raw),o[0],raw)
        v=M.open_manifest(self.p,self.crypto.epoch_secret,a,app=h[0],space=h[1],epoch=h[2])
        if (v[5],v[6],v[7],v[9],v[10],v[11])!=(r[8],h[15],r[4],r[5],r[6],r[7]):raise E('FILE_ARTIFACT_INVALID')
        self._issued(op,r[9],objects._key(self.crypto.epoch_secret,decode(o[0]),True),o[1])
        count=len(v[12]);expected={'intent.cbor','manifest.cbor'}|{f'chunk-{i:04d}.cbor' for i in range(count)}
        for p in root.iterdir():
            safe(p)
            if p.name not in expected and not (p.name.startswith('.write-') and p.name.endswith('.part')):raise E('FILE_ARTIFACT_INVALID')
        pieces=[a];digest=hashlib.sha256();total=0
        for i in range(count):
            ca,plain=self._read_chunk(root/f'chunk-{i:04d}.cbor',r,self._header(r,h,i,min(M.CHUNK_BYTES,r[4]-i*M.CHUNK_BYTES)))
            if [ca.typed_id,ca.header_bytes]!=v[12][i]:raise E('FILE_CHUNK_SET')
            digest.update(plain);total+=len(plain);pieces.append(ca)
        if total!=r[4] or digest.digest()!=r[5]:raise E('FILE_HASH_MISMATCH')
        handle=StagedFile(op,r[9],r[8],a.typed_id,count,total)
        return handle,r,h,tuple(pieces)
    def load_staged(self,op):
        self._start()
        try:return self._all(op)[0]
        finally:self._end()
    def artifacts(self,handle):
        self._start()
        try:
            if type(handle) is not StagedFile:raise E('FILE_HANDLE_INVALID')
            result=self._all(handle.operation_id)
            if handle!=result[0]:raise E('FILE_HANDLE_INVALID')
            return result[3]
        finally:self._end()
    @staticmethod
    def _stat(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    def stage(self,op,header,payload,cache,source,*,name,media_type):
        self._start(True)
        fd=None
        try:
            h=decode(objects.change_header(header));self.crypto._input(op,h,payload,cache);M.metadata(name,media_type)
            try:source=Path(source)
            except (TypeError,ValueError):raise E('FILE_SOURCE_INVALID') from None
            source=safe(source)
            if source.is_relative_to(self.store._storage.root):raise E('UNSAFE_PATH')
            try:fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            except OSError:raise E('FILE_SOURCE_INVALID') from None
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):raise E('FILE_SOURCE_INVALID')
            if st.st_size>M.MAX_FILE_BYTES:raise E('FILE_LIMIT')
            with os.fdopen(fd,'rb') as f:
                fd=None;digest=hashlib.sha256();size=0
                while data:=f.read(M.CHUNK_BYTES):
                    size+=len(data)
                    if size>M.MAX_FILE_BYTES:raise E('FILE_LIMIT')
                    digest.update(data)
                if size!=st.st_size or self._stat(os.fstat(f.fileno()))!=self._stat(st):raise E('FILE_SOURCE_CHANGED')
                r=self._record(op,h,payload,cache,size,digest.digest(),name,media_type)
                root=safe(self.store._storage.root/'staging'/'files'/self._subop(op).hex())
                if (root/'intent.cbor').exists():
                    _,old,_=self._read_record(op)
                    if r!=old:raise E('FILE_OPERATION_CONFLICT')
                if (root/'manifest.cbor').exists():
                    result=self._all(op)
                    for p in root.iterdir():
                        if not p.name.endswith('.part'):durable_existing(p)
                    return result[0]
                # Generating new ciphertext needs current authority, unlike reading a receipt.
                self.store._authorize(self.blob.certificate,h,self.p.sign_public(self.crypto.signing_seed),self.crypto.epoch_secret)
                root=self._directory(op,create=True)
                if not (root/'intent.cbor').exists():
                    try:raw=self.crypto._seal_local('file-intent',self._subop(op),r[9],hashed('file-local/journal',[op]),encode(r))
                    except StoreError as e:
                        if e.code=='OPERATION_CONFLICT':raise E('FILE_OPERATION_CONFLICT') from None
                        raise
                    self._notify('file.intent.sealed');publish(root/'intent.cbor',raw,self._notify,'file.intent')
                count=(size+M.CHUNK_BYTES-1)//M.CHUNK_BYTES
                expected={'intent.cbor','manifest.cbor'}|{f'chunk-{i:04d}.cbor' for i in range(count)}
                clean_unacknowledged(root,expected)
                self._notify('file.source.scanned');f.seek(0);second=hashlib.sha256();pairs=[]
                if self._stat(os.fstat(f.fileno()))!=self._stat(st):raise E('FILE_SOURCE_CHANGED')
                for i in range(count):
                    length=min(M.CHUNK_BYTES,size-i*M.CHUNK_BYTES);data=f.read(length)
                    if len(data)!=length:raise E('FILE_SOURCE_CHANGED')
                    second.update(data);bh=self._header(r,h,i,length);path=root/f'chunk-{i:04d}.cbor'
                    if path.exists():
                        a,old=self._read_chunk(path,r,bh)
                        if old!=data:raise E('FILE_SOURCE_CHANGED')
                        durable_existing(path)
                    else:a=self._seal(r,bh,data,f'file.chunk.{i}',path)
                    pairs.append([a.typed_id,a.header_bytes])
                if f.read(1) or second.digest()!=r[5] or self._stat(os.fstat(f.fileno()))!=self._stat(st):raise E('FILE_SOURCE_CHANGED')
                v={0:1,1:'file-manifest-local',2:h[0],3:h[1],4:h[2],5:r[8],6:h[15],7:size,8:M.CHUNK_BYTES,9:r[5],10:name,11:media_type,12:pairs}
                plain=M.dumps(v);bh=M.root_header(v,len(plain))
                self._seal(r,bh,plain,'file.manifest',root/'manifest.cbor')
                result=self._all(op);self._notify('file.stage.ack');return result[0]
        except OSError:raise E('FILE_IO_FAILED') from None
        finally:
            if fd is not None:os.close(fd)
            self._end()
    def commit(self,handle,header,payload,cache):
        self._start()
        try:
            if type(handle) is not StagedFile:raise E('FILE_HANDLE_INVALID')
            actual,r,h,parts=self._all(handle.operation_id)
            if handle!=actual:raise E('FILE_HANDLE_INVALID')
            given=decode(objects.change_header(header))
            if r[2]!=objects.change_header(given) or self.crypto._input(handle.operation_id,given,payload,cache)!=r[3]:raise E('FILE_OPERATION_CONFLICT')
            old=self.blob.read_committed(handle.operation_id,given,payload,cache,attachments=parts)
            if old is not None:return old
            self._notify('file.commit.before_prepare')
            p=self.blob.prepare(handle.operation_id,given,payload,cache,attachments=parts)
            self._notify('file.commit.prepared');result=self.store.commit(p)
            try:self._notify('file.commit.ack')
            except E:raise E('FILE_COMMIT_OUTCOME_UNKNOWN') from None
            return result
        finally:self._end()
    def write(self,op,header,payload,cache,source,*,name,media_type):
        # Own input before any user observer can mutate the original dictionary.
        header=decode(objects.change_header(header))
        s=self.stage(op,header,payload,cache,source,name=name,media_type=media_type)
        return self.commit(s,header,payload,cache)
