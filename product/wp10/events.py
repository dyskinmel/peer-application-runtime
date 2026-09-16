"""Encrypted local immutable event stream, explicit acknowledged pull delivery.

A single cooperating owner holds both the existing AuthorityStore and this
journal. The two databases are NOT one transaction. No remote ingestion, global
ordering, automatic GC, callback exactly-once, replay after OUTCOME_UNKNOWN,
secure erasure or anti-rollback hardware is supplied by this candidate.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from par_wire.codec import encode, decode
from par_store.fs import safe, sync_dir, WriterLock
from par_store.errors import StoreError
from par_crypto.primitives import domain, hashed, hkdf_extract, hkdf_expand, random_bytes

PROFILE = 'par-local-durable-events-0037'
MAX_PAYLOAD = 16384
MAX_EVENT_BYTES = 32768
MAX_PARENTS = 16
DDL = (
 'CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), generation BLOB NOT NULL, context BLOB NOT NULL, tail INTEGER NOT NULL, chain BLOB NOT NULL, issued INTEGER NOT NULL, nonce_chain BLOB NOT NULL, seal BLOB NOT NULL) STRICT',
 'CREATE TABLE nonces (reservation INTEGER PRIMARY KEY, nonce BLOB NOT NULL UNIQUE, operation BLOB NOT NULL, chain BLOB NOT NULL) STRICT',
 'CREATE TABLE events (sequence INTEGER PRIMARY KEY, operation BLOB NOT NULL UNIQUE, input_digest BLOB NOT NULL, event_id BLOB NOT NULL UNIQUE, record BLOB NOT NULL, chain BLOB NOT NULL) STRICT',
 'CREATE TABLE consumers (consumer BLOB PRIMARY KEY, position INTEGER NOT NULL, event_id BLOB NOT NULL, revision INTEGER NOT NULL, seal BLOB NOT NULL) STRICT',
)

class EventError(Exception):
    def __init__(self, code: str, operation_id: bytes | None = None):
        self.code, self.operation_id = code, operation_id
        super().__init__(code)  # Never include payload, raw SQL or arbitrary callback errors.

def need(ok, code='INVALID_INPUT'):
    if not ok: raise EventError(code)

def fixed(value, n): need(type(value) is bytes and len(value)==n)

def sha(raw): return hashlib.sha256(raw).digest()

def schema_bytes(schema):
    need(type(schema) is dict and 1<=len(schema)<=16, 'SCHEMA_INVALID')
    for k,v in schema.items():
        need(type(k) is str and re.fullmatch(r'[a-z][a-z0-9_]{0,31}',k) is not None and
             type(v) is str and v in ('text','uint64','int64','bool','bytes'), 'SCHEMA_INVALID')
    return encode([[k,schema[k]] for k in sorted(schema)])

def validate_payload(schema, payload):
    need(type(payload) is dict and set(payload)==set(schema), 'SCHEMA_INVALID')
    for k,t in schema.items():
        v=payload[k]
        ok=(t=='text' and type(v) is str or t=='uint64' and type(v) is int and 0<=v<2**64 or
            t=='int64' and type(v) is int and -(2**63)<=v<2**63 or
            t=='bool' and type(v) is bool or t=='bytes' and type(v) is bytes)
        need(ok,'SCHEMA_INVALID')
        if type(v) in (str,bytes):
            try: length=len(v.encode('utf8')) if type(v) is str else len(v)
            except UnicodeError: raise EventError('SCHEMA_INVALID') from None
            need(length<=MAX_PAYLOAD,'RESOURCE_LIMIT')
    raw=encode([[k,{'text':0,'uint64':1,'int64':2,'bool':3,'bytes':4}[schema[k]],
                 ((payload[k]<<1) if payload[k]>=0 else ((-payload[k]<<1)-1)) if schema[k]=='int64' else payload[k]]
                for k in sorted(payload)]);need(len(raw)<=MAX_PAYLOAD,'RESOURCE_LIMIT');return raw

def decode_payload(raw):
    try:
        pairs=decode(raw,max_bytes=MAX_PAYLOAD)
        need(type(pairs) is list and 1<=len(pairs)<=16,'SCHEMA_INVALID')
        need(all(type(p) is list and len(p)==3 and type(p[0]) is str and type(p[1]) is int for p in pairs),'SCHEMA_INVALID')
        keys=[p[0] for p in pairs];need(keys==sorted(set(keys)),'SCHEMA_INVALID')
        out={}
        for key,kind,value in pairs:
            valid=(kind==0 and type(value) is str or kind in (1,2) and type(value) is int and 0<=value<2**64 or
                   kind==3 and type(value) is bool or kind==4 and type(value) is bytes)
            need(valid,'SCHEMA_INVALID')
            out[key]=((value>>1) if value%2==0 else -(value>>1)-1) if kind==2 else value
        return out
    except EventError:raise
    except Exception:raise EventError('SCHEMA_INVALID') from None

@dataclass(frozen=True)
class EventReceipt:
    state: str
    operation_id: bytes
    event_id: bytes | None = None
    sequence: int | None = None
    replicated: bool = False
    cancellation_requested: bool = False

@dataclass(frozen=True)
class Event:
    sequence: int
    event_id: bytes
    operation_id: bytes
    parents: tuple[bytes,...]
    payload: bytes  # Canonical encoded, immutable decrypted bytes; not a shared mutable dict.

@dataclass(frozen=True)
class Batch:
    events: tuple[Event,...]
    token: bytes | None
    has_more: bool

class EventJournal:
    @classmethod
    def create(cls, root, **kwargs): return cls(root, create=True, **kwargs)
    @classmethod
    def open(cls, root, **kwargs): return cls(root, create=False, **kwargs)

    def __init__(self, root, *, owner, certificate, sign_seed, local_secret, app_id,
                 space_id, stream_id, epoch, schema, max_events=1024,
                 max_bytes=8*1024*1024, max_consumers=64, allow_legacy_experiment=False,
                 create=False, observer=None):
        fixed(sign_seed,32);fixed(local_secret,32);fixed(space_id,32);fixed(stream_id,32)
        need(type(certificate) is bytes and 0<len(certificate)<=4096)
        need(type(app_id) is str and re.fullmatch('[a-z0-9][a-z0-9.-]{0,127}',app_id) is not None)
        need(type(epoch) is int and 1<=epoch<2**64)
        for x,lo,hi in ((max_events,1,4096),(max_bytes,1024,64*1024*1024),(max_consumers,1,128)):
            need(type(x) is int and lo<=x<=hi)
        need(type(allow_legacy_experiment) is bool)
        self._schema=dict(decode(schema_bytes(schema))); self._owner=owner; self._p=owner._provider
        if self._p.identity.get('legacy_experiment') and not allow_legacy_experiment:
            raise EventError('DEPENDENCY_UPGRADE_REQUIRED')
        self._certificate=certificate;self._seed=sign_seed;self._public=self._p.sign_public(sign_seed)
        self._space=space_id;self._epoch=epoch;self._app=app_id
        from par_auth.membership import member_certificate
        owner._enter();row,state=owner._load(space_id)
        cert=member_certificate(self._p,app_id,state.membership,certificate)
        need(cert[3]==self._public,'SIGNER_MISMATCH')
        self._identity=(os.getpid(),threading.get_ident());self._closed=False;self._busy=False;self._uncertain=False
        self._session=random_bytes(16);self._subs={};self._known={};self._known_tail=0;self._known_chain=b''
        self.observer=observer;self._lock=None;self._connection=None
        self._context=encode([PROFILE,app_id,space_id,stream_id,epoch,schema_bytes(schema),sha(certificate),max_events,max_bytes,max_consumers])
        self._max_events=max_events;self._max_bytes=max_bytes;self._max_consumers=max_consumers
        self._root=safe(Path(root));self._path=self._root/'events.sqlite3'
        try:
            if create: self._root.mkdir(mode=0o700, parents=False, exist_ok=False)
            self._private(self._root, True)
            try:self._lock=WriterLock(self._root)
            except StoreError as e:raise EventError(e.code) from None
            if create:
                fd=os.open(self._path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd)
            self._private(self._path)
            self._connection=sqlite3.connect(self._path,isolation_level=None,timeout=0)
            self._connection.row_factory=sqlite3.Row
            c=self._connection
            c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA foreign_keys=ON')
            need(c.execute('PRAGMA journal_mode=DELETE').fetchone()[0]=='delete','UNSUPPORTED_JOURNAL')
            c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA busy_timeout=0')
            if create:
                self._generation=random_bytes(32);self._derive(local_secret)
                c.execute('BEGIN IMMEDIATE')
                for sql in DDL:c.execute(sql)
                c.execute('PRAGMA user_version=1')
                self._set_meta(0,b'',0,b'');c.execute('COMMIT');sync_dir(self._root)
            else:
                row=c.execute('SELECT * FROM metadata WHERE id=1').fetchone();need(row is not None,'JOURNAL_CORRUPT')
                self._generation=row['generation'];fixed(self._generation,32);self._derive(local_secret)
                need(row['context']==self._context and hmac.compare_digest(row['seal'],self._meta_seal(row['tail'],row['chain'],row['issued'],row['nonce_chain'])),'KEY_OR_CONTEXT_MISMATCH')
            self._schema_digest=self._actual_schema()
            need(self._schema_digest==self._expected_schema(),'JOURNAL_CORRUPT')
            self._audit();self._guard(False)
            self._file_identity=self._path_identity()
        except BaseException:
            if self._connection is not None:self._connection.close()
            if self._lock is not None:self._lock.close()
            self._closed=True
            raise

    @staticmethod
    def _private(path, directory=False):
        try:
            safe(path);s=os.lstat(path)
            need((stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) and
                 s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==(0o700 if directory else 0o600) and
                 (directory or s.st_nlink==1),'UNSAFE_PATH')
        except OSError:raise EventError('UNSAFE_PATH') from None

    def _path_identity(self):
        return tuple((p.stat().st_dev,p.stat().st_ino) for p in (self._root,self._path,self._root/'.store.lock'))

    def _derive(self,secret):
        self._key=hkdf_expand(hkdf_extract(sha(self._generation+self._context),secret),b'PAR local events 0037',32)
        self._mac_key=hkdf_expand(self._key,b'journal and cursor authentication',32)
    def _mac(self,label,parts):return hmac.digest(self._mac_key,domain(label,parts),'sha256')
    def _meta_seal(self,tail,chain,issued,nonce_chain):
        return self._mac('events/meta',[self._generation,self._context,tail,chain,issued,nonce_chain])
    def _set_meta(self,tail,chain,issued=None,nonce_chain=None):
        if issued is None:
            row=self._connection.execute('SELECT issued,nonce_chain FROM metadata WHERE id=1').fetchone()
            issued,nonce_chain=row
        self._connection.execute('INSERT OR REPLACE INTO metadata VALUES(1,?,?,?,?,?,?,?)',
            (self._generation,self._context,tail,chain,issued,nonce_chain,self._meta_seal(tail,chain,issued,nonce_chain)))
    def _actual_schema(self):
        return tuple(tuple(x) for x in self._connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"))
    @staticmethod
    def _expected_schema():
        with sqlite3.connect(':memory:') as c:
            for sql in DDL:c.execute(sql)
            return tuple(c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"))
    def _guard(self,write):
        try:
            self._owner._enter(write)
            need(self._space not in self._owner._failed,'NOT_AUTHORIZED')
            row,st=self._owner._load(self._space)
            permit=st.authorize(self._certificate,'write' if write else 'read')
            need(st.app_id==self._app and st.epoch==self._epoch,'NOT_AUTHORIZED')
            return encode([row['row_digest'],self._owner._storage.fencing_token,permit.device_id])
        except EventError:raise
        except Exception:raise EventError('NOT_AUTHORIZED') from None
    def _recheck(self,stamp,write=False):
        try:now=self._guard(write)
        except EventError:raise EventError('AUTHORITY_CHANGED') from None
        need(now==stamp,'AUTHORITY_CHANGED')
    def _enter(self):
        need((os.getpid(),threading.get_ident())==self._identity,'WRONG_OWNER')
        need(not self._closed,'CLOSED');need(not self._uncertain,'JOURNAL_UNCERTAIN');need(not self._busy,'REENTRANT_OPERATION')
        self._private(self._root,True);self._private(self._path);self._private(self._root/'.store.lock')
        need(self._path_identity()==self._file_identity,'PATH_CHANGED')
    @contextmanager
    def _operation(self,write=False):
        self._enter();self._busy=True
        try:
            stamp=self._guard(write);self._audit();yield stamp
        finally:self._busy=False
    def _notify(self,stage):
        if self.observer:self.observer(stage)
    def close(self):
        need((os.getpid(),threading.get_ident())==self._identity,'WRONG_OWNER')
        need(not self._busy,'REENTRANT_OPERATION')
        if not self._closed:
            self._connection.close();self._lock.close();self._seed=None;self._key=None;self._mac_key=None;self._closed=True;self._subs.clear()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()

    def _decode_event(self,row):
        obj=decode(row['record'],max_bytes=MAX_EVENT_BYTES)
        need(type(obj) is dict and set(obj)=={0,1,2},'JOURNAL_CORRUPT')
        header=obj[0];cipher=obj[1];sig=obj[2]
        need(type(header) is dict and set(header)==set(range(7)),'JOURNAL_CORRUPT')
        need(header[0]==self._context and header[1]==row['operation'] and header[2]==row['sequence'],'JOURNAL_CORRUPT')
        parents=header[3];need(type(parents) is list and len(parents)<=MAX_PARENTS and len(set(parents))==len(parents),'JOURNAL_CORRUPT')
        for p in parents:fixed(p,32)
        fixed(header[4],24);need(header[5]==self._certificate and header[6]==row['input_digest'],'JOURNAL_CORRUPT')
        self._p.verify(self._public,domain('events/sign',[header,cipher]),sig)
        need(row['event_id']==hashed('events/id',[row['record']]),'JOURNAL_CORRUPT')
        nonce=self._connection.execute('SELECT operation FROM nonces WHERE nonce=?',(header[4],)).fetchone()
        need(nonce is not None and nonce[0]==row['operation'],'JOURNAL_CORRUPT')
        raw=self._p.open(self._key,header[4],domain('events/aad',[header]),cipher)
        payload=decode_payload(raw);need(validate_payload(self._schema,payload)==raw,'JOURNAL_CORRUPT')
        need(row['input_digest']==self._mac('events/input',[row['operation'],parents,raw]),'JOURNAL_CORRUPT')
        return Event(row['sequence'],row['event_id'],row['operation'],tuple(parents),raw)

    def _consumer_seal(self,consumer,position,event_id,revision):
        return self._mac('events/consumer',[self._generation,consumer,position,event_id,revision])
    def _audit(self):
        try:
            c=self._connection
            need(self._actual_schema()==self._expected_schema() and c.execute('PRAGMA user_version').fetchone()[0]==1,'JOURNAL_CORRUPT')
            meta=c.execute('SELECT * FROM metadata').fetchall();need(len(meta)==1,'JOURNAL_CORRUPT');m=meta[0]
            need(m['generation']==self._generation and m['context']==self._context and hmac.compare_digest(m['seal'],self._meta_seal(m['tail'],m['chain'],m['issued'],m['nonce_chain'])),'JOURNAL_CORRUPT')
            rows=c.execute('SELECT * FROM events ORDER BY sequence LIMIT ?', (self._max_events+1,)).fetchall()
            need(len(rows)<=self._max_events and sum(len(r['record']) for r in rows)<=self._max_bytes,'JOURNAL_CORRUPT')
            nonces=c.execute('SELECT * FROM nonces ORDER BY reservation LIMIT 4097').fetchall()
            need(len(nonces)<=4096 and m['issued']==len(nonces),'JOURNAL_CORRUPT')
            nc=b''
            for n,r in enumerate(nonces,1):
                fixed(r['nonce'],24);fixed(r['operation'],16)
                nc=self._mac('events/nonce-chain',[nc,n,r['nonce'],r['operation']])
                need(r['reservation']==n and hmac.compare_digest(r['chain'],nc),'JOURNAL_CORRUPT')
            need(m['nonce_chain']==nc,'JOURNAL_CORRUPT')
            chain=b'';seen=set();ids={0:b''}
            for n,r in enumerate(rows,1):
                e=self._decode_event(r);need(e.sequence==n and all(p in seen for p in e.parents),'JOURNAL_CORRUPT')
                chain=self._mac('events/chain',[chain,n,e.operation_id,r['input_digest'],e.event_id])
                need(r['chain']==chain,'JOURNAL_CORRUPT');seen.add(e.event_id);ids[n]=e.event_id
            need(m['tail']==len(rows) and m['chain']==chain,'JOURNAL_CORRUPT')
            need(len(rows)>=self._known_tail,'JOURNAL_CORRUPT')
            if len(rows)==self._known_tail:need(chain==self._known_chain,'JOURNAL_CORRUPT')
            consumers=c.execute('SELECT * FROM consumers LIMIT ?',(self._max_consumers+1,)).fetchall()
            need(len(consumers)<=self._max_consumers,'JOURNAL_CORRUPT')
            for r in consumers:
                fixed(r['consumer'],16)
                need(r['position'] in ids and r['event_id']==ids[r['position']] and r['revision']>=0 and
                     hmac.compare_digest(r['seal'],self._consumer_seal(r['consumer'],r['position'],r['event_id'],r['revision'])),'JOURNAL_CORRUPT')
                known=self._known.get(r['consumer'])
                if known:need(r['position']>=known[0] and r['revision']>=known[1],'JOURNAL_CORRUPT')
            need(set(self._known)<=set(r['consumer'] for r in consumers),'JOURNAL_CORRUPT')
            self._known_tail=len(rows);self._known_chain=chain
            self._known={r['consumer']:(r['position'],r['revision']) for r in consumers}
            return rows
        except EventError as e:
            if e.code=='JOURNAL_CORRUPT':raise
            raise EventError('JOURNAL_CORRUPT') from None
        except Exception:raise EventError('JOURNAL_CORRUPT') from None

    def inspect(self):
        with self._operation() as stamp:
            c=self._connection
            result={'scope':'LOCAL_ONLY','events':c.execute('SELECT count(*) FROM events').fetchone()[0],
                    'nonces':c.execute('SELECT count(*) FROM nonces').fetchone()[0],
                    'consumers':c.execute('SELECT count(*) FROM consumers').fetchone()[0],
                    'bytes':c.execute('SELECT coalesce(sum(length(record)),0) FROM events').fetchone()[0],
                    'global_order':False,'automatic_gc':False,'presence_replayed':False}
            self._recheck(stamp);return result
    def _receipt(self,row):return EventReceipt('LOCAL_EVENT_COMMITTED',row['operation'],row['event_id'],row['sequence'])
    def inspect_operation(self,operation_id):
        fixed(operation_id,16)
        with self._operation() as stamp:
            row=self._connection.execute('SELECT * FROM events WHERE operation=?',(operation_id,)).fetchone()
            self._recheck(stamp);return None if row is None else self._receipt(row)

    def _transaction(self,body,stamp,*,write=False,stage='event',operation=None):
        c=self._connection;attempted=False
        try:
            c.execute('BEGIN IMMEDIATE');self._notify(stage+'.after_begin')
            result=body();self._notify(stage+'.before_commit');self._recheck(stamp,write)
            attempted=True;c.execute('COMMIT');self._notify(stage+'.after_commit')
            self._audit()  # Bind the observed durable tail/cursor immediately, not at the next caller.
            return result
        except BaseException as e:
            try:
                if c.in_transaction:c.execute('ROLLBACK')
            except sqlite3.Error:self._uncertain=True
            if attempted or self._uncertain:
                self._uncertain=True;raise EventError('EVENT_OUTCOME_UNKNOWN',operation) from None
            if isinstance(e,sqlite3.Error):
                code=getattr(e,'sqlite_errorcode',0)&255
                raise EventError({sqlite3.SQLITE_BUSY:'STORAGE_BUSY',sqlite3.SQLITE_LOCKED:'STORAGE_BUSY',sqlite3.SQLITE_FULL:'STORAGE_FULL'}.get(code,'STORAGE_ERROR'),operation) from None
            if isinstance(e,OSError):raise EventError('STORAGE_ERROR',operation) from None
            raise

    def publish(self,operation_id,payload,*,parents=(),cancelled=None):
        fixed(operation_id,16)
        need(type(parents) in (tuple,list) and len(parents)<=MAX_PARENTS)
        for parent in parents:fixed(parent,32)
        need(len(set(parents))==len(parents));parents=tuple(sorted(parents))
        raw=validate_payload(self._schema,payload)
        need(cancelled is None or callable(cancelled))
        def cancel():
            if cancelled is None:return False
            try:out=cancelled();need(type(out) is bool);return out
            except Exception:raise EventError('CANCEL_PROBE_FAILED',operation_id) from None
        with self._operation(write=True) as stamp:
            c=self._connection;dg=self._mac('events/input',[operation_id,list(parents),raw])
            old=c.execute('SELECT * FROM events WHERE operation=?',(operation_id,)).fetchone()
            if old is not None:
                need(old['input_digest']==dg,'OPERATION_CONFLICT');self._recheck(stamp,True);return self._receipt(old)
            for parent in parents:need(c.execute('SELECT 1 FROM events WHERE event_id=?',(parent,)).fetchone() is not None,'DEPENDENCIES_PENDING')
            tail=c.execute('SELECT tail FROM metadata').fetchone()[0]
            need(tail<self._max_events,'RESOURCE_LIMIT')
            need(c.execute('SELECT count(*) FROM nonces').fetchone()[0]<4096,'RESOURCE_LIMIT')
            # Conservative exact-input bound reserves room for signature/header before nonce.
            used=c.execute('SELECT coalesce(sum(length(record)),0) FROM events').fetchone()[0]
            need(used+len(raw)+len(self._context)+len(self._certificate)+len(parents)*34+512<=self._max_bytes,'RESOURCE_LIMIT')
            if cancel():return EventReceipt('CANCELLED',operation_id)
            nonce=random_bytes(24)
            def reserve():
                m=c.execute('SELECT * FROM metadata').fetchone();number=m['issued']+1
                nc=self._mac('events/nonce-chain',[m['nonce_chain'],number,nonce,operation_id])
                c.execute('INSERT INTO nonces VALUES(?,?,?,?)',(number,nonce,operation_id,nc))
                self._set_meta(m['tail'],m['chain'],number,nc)
            self._transaction(reserve,stamp,write=True,stage='nonce',operation=operation_id)
            header={0:self._context,1:operation_id,2:tail+1,3:list(parents),4:nonce,5:self._certificate,6:dg}
            ciphertext=self._p.seal(self._key,nonce,domain('events/aad',[header]),raw)
            record=encode({0:header,1:ciphertext,2:self._p.sign(self._seed,domain('events/sign',[header,ciphertext]))})
            need(len(record)<=MAX_EVENT_BYTES,'RESOURCE_LIMIT');eid=hashed('events/id',[record])
            try:self._notify('event.after_encrypt')
            except OSError:raise EventError('STORAGE_ERROR',operation_id) from None
            if cancel():return EventReceipt('CANCELLED',operation_id)
            def commit():
                m=c.execute('SELECT * FROM metadata').fetchone();need(m['tail']==tail,'STALE_FRONTIER')
                chain=self._mac('events/chain',[m['chain'],tail+1,operation_id,dg,eid])
                c.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(tail+1,operation_id,dg,eid,record,chain));self._notify('event.after_insert')
                self._set_meta(tail+1,chain);self._notify('event.after_frontier')
            self._transaction(commit,stamp,write=True,operation=operation_id)
            try:requested=cancel()
            except EventError:
                self._uncertain=True;raise EventError('EVENT_OUTCOME_UNKNOWN',operation_id) from None
            return EventReceipt('LOCAL_EVENT_COMMITTED',operation_id,eid,tail+1,False,requested)

    def _row(self,consumer):
        r=self._connection.execute('SELECT * FROM consumers WHERE consumer=?',(consumer,)).fetchone()
        need(r is not None,'JOURNAL_CORRUPT');return r
    def _token(self,label,data):
        raw=encode(data);return encode([raw,self._mac(label,[raw])])
    def _untoken(self,label,token):
        try:
            need(type(token) is bytes and len(token)<=4096,'CURSOR_INVALID')
            pair=decode(token,max_bytes=4096);need(type(pair) is list and len(pair)==2,'CURSOR_INVALID')
            raw,mac=pair;need(type(raw) is bytes and type(mac) is bytes and hmac.compare_digest(mac,self._mac(label,[raw])),'CURSOR_INVALID')
            return decode(raw,max_bytes=4096)
        except Exception:raise EventError('CURSOR_INVALID') from None
    def subscribe(self,consumer_id,*,expected_cursor=None):
        fixed(consumer_id,16)
        with self._operation() as stamp:
            need(consumer_id not in self._subs,'SUBSCRIPTION_BUSY');c=self._connection
            r=c.execute('SELECT * FROM consumers WHERE consumer=?',(consumer_id,)).fetchone()
            if expected_cursor is not None:
                data=self._untoken('events/cursor',expected_cursor)
                need(type(data) is list and len(data)==6 and data[:3]==[self._generation,sha(self._context),consumer_id], 'CURSOR_INVALID')
                need(r is not None and type(data[3]) is int and type(data[5]) is int and r['position']>=data[3] and r['revision']>=data[5],'CURSOR_INVALID')
                e=c.execute('SELECT event_id FROM events WHERE sequence=?',(data[3],)).fetchone()
                need((data[3]==0 and data[4]==b'') or (e is not None and e[0]==data[4]),'CURSOR_INVALID')
            if r is None:
                need(c.execute('SELECT count(*) FROM consumers').fetchone()[0]<self._max_consumers,'RESOURCE_LIMIT')
                self._transaction(lambda:c.execute('INSERT INTO consumers VALUES(?,0,?,0,?)',(consumer_id,b'',self._consumer_seal(consumer_id,0,b'',0))),stamp,stage='subscribe')
            self._recheck(stamp);sub=Subscription(self,consumer_id);self._subs[consumer_id]=sub;return sub

class Subscription:
    """One outstanding bounded delivery. Ack only after the consumer's own work.

    Poll never advances durable position. A crash before ack redelivers. Ack and
    external side effects are not one transaction; consumers must be idempotent.
    """
    def __init__(self,journal,consumer):
        self._journal=journal;self._consumer=consumer;self._closed=False;self._pending=None;self._stamp=None;self._last=None
        self._session=random_bytes(16)
    def _check(self):
        self._journal._enter();need(not self._closed,'SUBSCRIPTION_CLOSED')
    @property
    def position(self):
        self._check()
        with self._journal._operation():return self._journal._row(self._consumer)['position']
    def poll(self,*,limit=16,byte_limit=256*1024):
        self._check();need(type(limit) is int and 1<=limit<=32 and type(byte_limit) is int and 1<=byte_limit<=512*1024)
        j=self._journal
        with j._operation() as stamp:
            if self._pending is not None:
                j._recheck(self._stamp);return self._pending
            r=j._row(self._consumer);c=j._connection
            rows=c.execute('SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?',(r['position'],limit+1)).fetchall()
            events=[];size=0
            for row in rows[:limit]:
                e=j._decode_event(row)
                if size+len(e.payload)>byte_limit:
                    need(bool(events),'EVENT_EXCEEDS_WINDOW');break
                events.append(e);size+=len(e.payload)
            j._recheck(stamp)
            if not events:return Batch((),None,False)
            data=[j._generation,sha(j._context),self._consumer,self._session,r['position'],r['revision'],events[-1].sequence,events[-1].event_id,stamp]
            token=j._token('events/delivery',data)
            b=Batch(tuple(events),token,len(rows)>len(events));self._pending=b;self._stamp=stamp;return b
    def ack(self,token):
        self._check();j=self._journal
        with j._operation() as stamp:
            data=j._untoken('events/delivery',token)
            need(type(data) is list and len(data)==9 and data[:4]==[j._generation,sha(j._context),self._consumer,self._session],'CURSOR_INVALID')
            if self._last is not None and token==self._last[0]:
                j._recheck(data[8]);return self._last[1]
            need(self._pending is not None and token==self._pending.token,'CURSOR_INVALID')
            j._recheck(data[8]);r=j._row(self._consumer)
            need((r['position'],r['revision'])==(data[4],data[5]),'CURSOR_STALE')
            def commit():
                revision=r['revision']+1
                j._connection.execute('UPDATE consumers SET position=?,event_id=?,revision=?,seal=? WHERE consumer=?',
                 (data[6],data[7],revision,j._consumer_seal(self._consumer,data[6],data[7],revision),self._consumer))
                j._notify('ack.after_update')
            j._transaction(commit,stamp,stage='ack')
            result=j._token('events/cursor',[j._generation,sha(j._context),self._consumer,data[6],data[7],r['revision']+1])
            self._pending=None;self._stamp=None;self._last=(token,result);return result
    def cursor(self):
        self._check();j=self._journal
        with j._operation() as stamp:
            r=j._row(self._consumer);j._recheck(stamp)
            return j._token('events/cursor',[j._generation,sha(j._context),self._consumer,r['position'],r['event_id'],r['revision']])
    def cancel(self):
        j=self._journal
        need((os.getpid(),threading.get_ident())==j._identity,'WRONG_OWNER');need(not j._busy,'REENTRANT_OPERATION')
        if not self._closed:
            self._closed=True;self._pending=None;self._stamp=None;self._last=None;j._subs.pop(self._consumer,None)
