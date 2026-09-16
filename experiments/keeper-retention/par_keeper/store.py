"""Private local opaque retention store. Not a public server or OS security boundary.

The cooperative lifetime writer lock serializes publication, reads and lifecycle
operations. There is deliberately no object deletion or quota refund operation.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib,os,sqlite3,stat,threading
from pathlib import Path
from par_store.fs import WriterLock,safe,sync_dir
from par_store.model import require_sqlite
from par_store.store import sqlite_error
from par_recovery.contract import object_id,MAX_INDEX,MAX_OBJECT,index_id,inspect_index
from par_recovery.transfer import read_file,put_file,mkdir
from .contract import *
from .clock import BootClock,Tick
from .errors import KeeperError as E

DDL=Path(__file__).resolve().parents[1]/'schema.sql'
APPLICATION_ID=1263555154
MAX_QUOTA=512*1024*1024

def _schema(c):
    return tuple(tuple(r) for r in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
def _expected_schema(path=DDL):
    c=sqlite3.connect(':memory:')
    try:c.executescript(path.read_text());return _schema(c)
    finally:c.close()
def _translate(ex):
    if isinstance(ex,E):return ex
    if isinstance(ex,sqlite3.Error):return E(sqlite_error(ex).code)
    if hasattr(ex,'code'):return E(ex.code)
    if isinstance(ex,OSError):return E('STORAGE_IO')
    return ex

class Keeper:
    DDL_PATH=DDL
    SCHEMA_VERSION=1
    def __init__(self,root,provider,signing_seed,authority,*,quota_bytes,max_leases=32,max_operations=4096,clock=None,allow_unpatched_sqlite=False,observer=None):
        self.connection=None;self._lock=None;self._closed=True;self._busy=False;self._uncertain=False
        self._thread=threading.get_ident();self.observer=observer;self.provider=provider;self._seed=signing_seed
        authority_body(authority);fixed(signing_seed);integer(quota_bytes,1,MAX_QUOTA);integer(max_leases,1,256);integer(max_operations,1,65536)
        require_sqlite(sqlite3.sqlite_version,allow_unpatched_sqlite)
        self.public=provider.sign_public(signing_seed);self.clock=clock or BootClock();self.authority=authority
        self.quota=quota_bytes;self.max_leases=max_leases;self.max_operations=max_operations
        self._last=None;self._clock_uncertain=False
        try:
            self.root=safe(Path(root));mkdir(self.root);self._lock=WriterLock(self.root)
            db=safe(self.root/'keeper.sqlite')
            for suffix in ('-wal','-shm','-journal'):safe(self.root/('keeper.sqlite'+suffix))
            if not db.exists():
                fd=os.open(db,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
            if not db.is_file():raise E('UNSAFE_PATH')
            c=sqlite3.connect(db.as_uri()+'?mode=rw',uri=True,timeout=.05,isolation_level=None);self.connection=c;c.row_factory=sqlite3.Row
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise E('CORRUPT_STORE')
            tables=_schema(c);version=c.execute('PRAGMA user_version').fetchone()[0]
            fresh=not tables and version==0
            if not fresh and (version!=self.SCHEMA_VERSION or c.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID or tables!=_expected_schema(self.DDL_PATH)):raise E('SCHEMA_MISMATCH')
            c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA temp_store=MEMORY');c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA busy_timeout=50')
            if fresh:
                tick=self._sample()
                c.executescript('BEGIN IMMEDIATE;\n'+self.DDL_PATH.read_text());self._emit('initialize.schema')
                c.execute('INSERT INTO metadata VALUES(1,?,?,?,?,?,?,?,?)',(hashlib.sha256(self.DDL_PATH.read_bytes()).digest(),self.public,dump(authority_body(authority)),quota_bytes,max_leases,max_operations,tick.boot,tick.ns))
                c.execute('PRAGMA user_version='+str(self.SCHEMA_VERSION));c.execute('PRAGMA application_id='+str(APPLICATION_ID));self._emit('initialize.before_commit');c.execute('COMMIT');sync_dir(self.root);self._emit('initialize.durable')
            row=c.execute('SELECT * FROM metadata').fetchone()
            if row is None or row['profile']!=hashlib.sha256(self.DDL_PATH.read_bytes()).digest():raise E('SCHEMA_MISMATCH')
            if row['keeper']!=self.public:raise E('KEEPER_IDENTITY')
            if row['authority']!=dump(authority_body(authority)):raise E('STALE_AUTHORITY')
            if (row['quota'],row['max_leases'],row['max_ops'])!=(quota_bytes,max_leases,max_operations):raise E('CONFIGURATION_MISMATCH')
            self._last=Tick(row['clock_boot'],row['clock_ns']);self._sample()
            mkdir(self.root/'objects');self._closed=False;self._validate_database();self._settings()
        except BaseException as ex:
            self.close();translated=_translate(ex)
            if translated is ex:raise
            raise translated from None
    def close(self):
        if self.connection is not None:
            try:self.connection.close()
            finally:self.connection=None
        if self._lock is not None:self._lock.close();self._lock=None
        self._closed=True
    def __enter__(self):return self
    def __exit__(self,*a):self.close()
    def _emit(self,event):
        if self.observer is not None:self.observer(event)
    def _settings(self):
        c=self.connection
        if tuple(c.execute('PRAGMA '+p).fetchone()[0] for p in ('journal_mode','synchronous','foreign_keys','temp_store'))!=('wal',2,1,2):raise E('SETTINGS_MISMATCH')
    @contextmanager
    def _operation(self):
        if self._closed:raise E('CLOSED')
        if threading.get_ident()!=self._thread:raise E('WRONG_THREAD')
        if self._busy:raise E('REENTRANT_OPERATION')
        if self._uncertain:raise E('STORAGE_UNCERTAIN')
        self._settings();self._busy=True
        try:yield
        except BaseException as ex:
            tr=_translate(ex)
            if tr is ex:raise
            raise tr from None
        finally:self._busy=False
    def _sample(self):
        t=self.clock.sample()
        if type(t) is not Tick:raise E('CLOCK_UNCERTAIN')
        fixed(t.boot);integer(t.ns)
        if self._last is not None and self._last.boot==t.boot and t.ns<self._last.ns:self._clock_uncertain=True
        if self._last is None or self._last.boot!=t.boot or t.ns>=self._last.ns:self._last=t
        return t
    def _issue_tick(self,seconds):
        t=self._sample()
        if self._clock_uncertain or t.ns+seconds*10**9>I64:raise E('CLOCK_UNCERTAIN')
        return t
    def _transaction(self,label,fn):
        c=self.connection;committed=False;commit_started=False
        try:
            c.execute('BEGIN IMMEDIATE');self._emit(label+'.begin');answer=fn()
            self._emit(label+'.before_commit');commit_started=True;c.execute('COMMIT');committed=True
            self._emit(label+'.after_commit');self._emit(label+'.ack');return answer
        except BaseException as ex:
            if c.in_transaction:
                try:c.execute('ROLLBACK')
                except sqlite3.Error:self._uncertain=True
            if committed:raise E('OUTCOME_UNKNOWN') from None
            if commit_started:self._uncertain=True;raise E('OUTCOME_UNKNOWN') from None
            tr=_translate(ex)
            if tr is ex:raise
            raise tr from None
    def _lease(self,lid):
        fixed(lid);r=self.connection.execute('SELECT * FROM leases WHERE id=?',(lid,)).fetchone()
        if r is None:raise E('LEASE_UNKNOWN')
        return r
    @staticmethod
    def _pin(row):return pin_from(load(row['pin']))
    def _info(self,row):return inventory(row['index_raw'],self._pin(row))
    def _authorized(self,cap,call,action,lid,payload=None):
        req=verify_call(self.provider,self.authority,self.public,cap,call,action,lid,payload)
        if self.connection.execute('SELECT authority FROM metadata').fetchone()[0]!=dump(authority_body(self.authority)):raise E('STALE_AUTHORITY')
        cb,_=split(cap)
        row=None if lid is None else self._lease(lid)
        if row is not None:
            if cb[5]!=self._pin(row).index_id:raise E('INDEX_SCOPE')
            if action in ('put','seal','renew','release') and cb[4]!=row['owner']:raise E('LEASE_OWNER')
        return req,cb,row
    @staticmethod
    def _opid(req):return hashed('keeper-local/operation-id',[req[4],req[7]])
    def _cached(self,req,cap,call):
        r=self.connection.execute('SELECT * FROM operations WHERE id=?',(self._opid(req),)).fetchone()
        if r is None:return None
        if r['request']!=call or r['capability']!=cap:raise E('OPERATION_CONFLICT')
        self._validate_response(r,self._lease(r['lease']))
        return r['response']
    def _validate_response(self,op,row):
        try:
            req,_=split(op['request'])
            if op['action']=='reserve':
                expected=hashed('keeper-local/lease-id',[self.public,req[4],req[7]])
                if expected!=row['id'] or op['response']!=expected or row['owner']!=req[4] or row['origin_nonce']!=req[7]:raise E('CORRUPT_STORE')
            elif op['action'] in ('seal','renew'):
                b=check_receipt(self.provider,op['response'],self.public,row['index_raw'],self._pin(row),row['id'])
                cap,_=split(op['capability'])
                if (b[14],b[15],b[16],b[24])!=(cap[2],row['origin_nonce'],req[7],req[3]) or b[17]>row['generation']:raise E('CORRUPT_STORE')
                if b[17]==row['generation'] and op['response']!=row['receipt']:raise E('CORRUPT_STORE')
            elif load(op['response'])!={0:'RELEASED_RETAINED',1:row['id'],2:req[7],3:False}:raise E('CORRUPT_STORE')
        except Exception:raise E('CORRUPT_STORE') from None
    def _record(self,req,cap,call,lid,response):
        if self.connection.execute('SELECT count(*) FROM operations').fetchone()[0]>=self.max_operations:raise E('OPERATION_LIMIT')
        self.connection.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',(self._opid(req),lid,req[5],call,cap,response))
    @staticmethod
    def _serving(row):
        if row['state']=='released':raise E('LEASE_RELEASED')
    def object_path(self,lid,oid):
        """Trusted-host diagnostic path only; no arbitrary peer-supplied path."""
        fixed(lid);fixed(oid);return safe(self.root/'objects'/lid.hex()/oid.hex())
    def _bytes(self,row,*,require_all=False):
        ds,_,_=self._info(row);expected={d[0]:(d[1],d[2]) for d in ds}
        records={r[0] for r in self.connection.execute('SELECT oid FROM stored_objects WHERE lease=?',(row['id'],))}
        if not records<=set(expected):raise E('CORRUPT_STORE')
        have={};bad=[]
        for oid in records:
            try:
                raw=read_file(self.object_path(row['id'],oid));kind,n=expected[oid]
                if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
                have[oid]=raw
            except Exception as ex:
                if not hasattr(ex,'code'):raise
                bad.append(oid)
        if require_all and (bad or set(have)!=set(expected)):raise E('INCOMPLETE')
        return have,bad
    def _receipt(self,row):
        if row['receipt'] is None:raise E('NOT_SEALED')
        b=check_receipt(self.provider,row['receipt'],self.public,row['index_raw'],self._pin(row),row['id'])
        if b[15]!=row['origin_nonce'] or b[17]!=row['generation'] or b[21]!=row['seconds']:raise E('CORRUPT_STORE')
        return b
    def _validate_database(self):
        c=self.connection
        if c.execute('PRAGMA foreign_key_check').fetchone() is not None:raise E('CORRUPT_STORE')
        if c.execute('SELECT count(*) FROM metadata').fetchone()[0]!=1:raise E('CORRUPT_STORE')
        rows=c.execute('SELECT * FROM leases').fetchall()
        if self._lease_limit_count()>self.max_leases or self._reserved_bytes()>self.quota:raise E('CORRUPT_STORE')
        try:
            for row in rows:
                ds,_,total=self._info(row)
                if row['charge']!=total+len(row['index_raw']):raise E('CORRUPT_STORE')
                fixed(row['owner']);fixed(row['origin_nonce'])
                if row['receipt'] is not None:self._receipt(row)
                expected={d[0] for d in ds}
                if any(r[0] not in expected for r in c.execute('SELECT oid FROM stored_objects WHERE lease=?',(row['id'],))):raise E('CORRUPT_STORE')
            ops=c.execute('SELECT * FROM operations').fetchall()
            if len(ops)>self.max_operations:raise E('CORRUPT_STORE')
            bylease={r['id']:[] for r in rows}
            for op in ops:
                bylease[op['lease']].append(op)
                req,_=split(op['request']);call_shape(req)
                if op['id']!=self._opid(req) or req[5]!=op['action'] or req[3]!=capability_id(op['capability']):raise E('CORRUPT_STORE')
                cap,_=split(op['capability']);capability_shape(cap)
                verify_capability(self.provider,authority_from(cap[2]),self.public,op['capability'])
                outer=load(op['request']);self.provider.verify(cap[4],domain('keeper-local/request-sign',[outer[0]]),outer[1])
                if req[4]!=cap[4]:raise E('CORRUPT_STORE')
                if op['action']=='reserve' and (op['response']!=op['lease'] or req[6] is not None):raise E('CORRUPT_STORE')
                if op['action']!='reserve' and req[6]!=op['lease']:raise E('CORRUPT_STORE')
                self._validate_response(op,self._lease(op['lease']))
            for row in rows:
                history=bylease[row['id']]
                if sum(o['action']=='reserve' for o in history)!=1:raise E('CORRUPT_STORE')
                receipt_ops=[o for o in history if o['action'] in ('seal','renew')]
                generations=sorted(split(o['response'])[0][17] for o in receipt_ops)
                if generations!=list(range(1,row['generation']+1)):raise E('CORRUPT_STORE')
                if bool(row['generation'])!=(sum(o['action']=='seal' for o in history)==1):raise E('CORRUPT_STORE')
                if (row['state']=='released')!=any(o['action']=='release' for o in history):raise E('CORRUPT_STORE')
        except Exception:raise E('CORRUPT_STORE') from None
    def reserve(self,index,pin,seconds,capability,call):
        payload=reserve_payload(index,pin,seconds)
        with self._operation():
            req,cap,_=self._authorized(capability,call,'reserve',None,payload)
            if cap[5]!=pin.index_id or (pin.app,pin.space)!=(self.authority.app,self.authority.space):raise E('INDEX_SCOPE')
            if seconds>cap[7]:raise E('DURATION_DENIED')
            ds,_,total=inventory(index,pin);charge=total+len(index)
            cached=self._cached(req,capability,call)
            if cached is not None:return cached
            lid=hashed('keeper-local/lease-id',[self.public,req[4],req[7]])
            def apply():
                if self._lease_limit_count()>=self.max_leases:raise E('LEASE_LIMIT')
                if self._reserved_bytes()+charge>self.quota:raise E('CAPACITY')
                self.connection.execute('INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,NULL)',(lid,index,dump(pin_values(pin)),req[4],req[7],seconds,charge,'reserved',0))
                self._record(req,capability,call,lid,lid);self._emit('reserve.recorded');return lid
            return self._transaction('reserve',apply)
    def put(self,lid,oid,raw,capability,call):
        payload=put_payload(oid,raw)
        with self._operation():
            req,cap,row=self._authorized(capability,call,'put',lid,payload);self._serving(row)
            expected={d[0]:(d[1],d[2]) for d in self._info(row)[0]}
            if oid not in expected:raise E('OBJECT_SCOPE')
            kind,n=expected[oid]
            if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
            mkdir(self.root/'objects'/lid.hex())
            path=self.object_path(lid,oid)
            if path.exists() and read_file(path)!=raw:raise E('OBJECT_HASH')
            put_file(path,raw,self.observer,prefix='object')
            def apply():
                self._authorized(capability,call,'put',lid,payload)
                if read_file(path)!=raw:raise E('OBJECT_HASH')
                self.connection.execute('INSERT OR IGNORE INTO stored_objects VALUES(?,?)',(lid,oid));self._emit('put.recorded');return 'STORED'
            return self._transaction('put',apply)
    def _complete(self,lid,seconds,capability,call,action):
        payload=None if action=='seal' else seconds
        with self._operation():
            req,cap,row=self._authorized(capability,call,action,lid,payload);self._serving(row)
            self._bytes(row,require_all=True)
            cached=self._cached(req,capability,call)
            if cached is not None:return cached
            if action=='seal' and row['state']!='reserved':raise E('ALREADY_SEALED')
            if action=='renew' and row['state']!='sealed':raise E('NOT_SEALED')
            seconds=row['seconds'] if action=='seal' else seconds;integer(seconds,1,MAX_SECONDS)
            if seconds>cap[7]:raise E('DURATION_DENIED')
            tick=self._issue_tick(seconds)
            if row['receipt'] is not None:
                old=self._receipt(row)
                if old[18]==tick.boot and tick.ns+seconds*10**9<old[20]:raise E('RETENTION_SHORTENING')
            body=receipt_body(row['index_raw'],self._pin(row),self.public,lid,self.authority,capability,call,row['origin_nonce'],row['generation']+1,tick,seconds)
            raw=signed(self.provider,self._seed,'receipt-sign',body);self._emit(action+'.signed')
            def apply():
                self._authorized(capability,call,action,lid,payload)
                self._bytes(row,require_all=True)
                self.connection.execute("UPDATE leases SET state='sealed',generation=?,seconds=?,receipt=? WHERE id=?",(body[17],seconds,raw,lid))
                self.connection.execute('UPDATE metadata SET clock_boot=?,clock_ns=?',(tick.boot,tick.ns))
                self._record(req,capability,call,lid,raw);self._emit(action+'.recorded');return raw
            return self._transaction(action,apply)
    def seal(self,lid,capability,call):return self._complete(lid,None,capability,call,'seal')
    def renew(self,lid,seconds,capability,call):
        integer(seconds,1,MAX_SECONDS);return self._complete(lid,seconds,capability,call,'renew')
    def release(self,lid,capability,call):
        with self._operation():
            req,cap,row=self._authorized(capability,call,'release',lid)
            cached=self._cached(req,capability,call)
            if cached is not None:return cached
            response=dump({0:'RELEASED_RETAINED',1:lid,2:req[7],3:False})
            def apply():
                self.connection.execute("UPDATE leases SET state='released' WHERE id=?",(lid,));self._record(req,capability,call,lid,response);self._emit('release.recorded');return response
            return self._transaction('release',apply)
    def _status(self,row):
        have,bad=self._bytes(row);ds,_,_=self._info(row);tick=self._sample()
        if row['state']=='released':state='RELEASED_RETAINED'
        elif bad or (row['state']=='sealed' and len(have)!=len(ds)):state='DEGRADED'
        elif row['receipt'] is None:state='AWAITING_OBJECTS' if len(have)!=len(ds) else 'BYTES_COMPLETE_UNSEALED'
        else:
            b=self._receipt(row)
            if self._clock_uncertain or b[18]!=tick.boot or tick.ns<b[19]:state='UNKNOWN_RETAINED'
            elif tick.ns>=b[20]:state='EXPIRED_RETAINED'
            else:state='RETAINED_ACTIVE'
        return {'state':state,'received':len(have),'expected':len(ds),'bad':len(bad),'reserved_bytes':row['charge'],'generation':row['generation'],
                'recipient_validated':False,'currently_network_reachable':None,'automatic_gc':False,'product_qualified':False}
    def status(self,lid,capability,call):
        with self._operation():
            _,_,row=self._authorized(capability,call,'status',lid);return self._status(row)
    def receipt(self,lid,capability,call):
        with self._operation():
            _,_,row=self._authorized(capability,call,'receipt',lid);self._serving(row);self._receipt(row);self._bytes(row,require_all=True);return row['receipt']
    def fetch(self,lid,oid,capability,call):
        fixed(oid)
        with self._operation():
            _,_,row=self._authorized(capability,call,'get',lid,oid);self._serving(row)
            ds={d[0]:(d[1],d[2]) for d in self._info(row)[0]}
            if oid not in ds:raise E('OBJECT_SCOPE')
            if self.connection.execute('SELECT 1 FROM stored_objects WHERE lease=? AND oid=?',(lid,oid)).fetchone() is None:raise E('INCOMPLETE')
            raw=read_file(self.object_path(lid,oid));kind,n=ds[oid]
            if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
            return raw
    def challenge(self,lid,nonce,capability,call):
        fixed(nonce)
        with self._operation():
            _,_,row=self._authorized(capability,call,'challenge',lid,nonce);self._serving(row);self._bytes(row,require_all=True)
            state=self._status(row);tick=self._sample()
            body={0:1,1:PROFILE,2:self.public,3:lid,4:nonce,5:hashed('keeper-local/call',[call]),6:self._pin(row).index_id,7:state['state'],8:False,9:tick.boot,10:tick.ns}
            return signed(self.provider,self._seed,'observation-sign',body)
    def update_authority(self,authority):
        """TRUSTED HOST ONLY, after external chain validation; never a client endpoint."""
        authority_body(authority)
        with self._operation():
            old=self.authority
            if (old.app,old.space)!=(authority.app,authority.space):raise E('CAPABILITY_SCOPE')
            if old==authority:return
            if authority.sequence<=old.sequence or authority.epoch<old.epoch:raise E('STALE_AUTHORITY')
            def apply():self.connection.execute('UPDATE metadata SET authority=?',(dump(authority_body(authority)),));self._emit('authority.recorded')
            try:self._transaction('authority',apply)
            except BaseException:self._uncertain=True;raise
            self.authority=authority
    def _reserved_bytes(self):
        return self.connection.execute('SELECT coalesce(sum(charge),0) FROM leases').fetchone()[0]
    def _lease_limit_count(self):
        return self.connection.execute('SELECT count(*) FROM leases').fetchone()[0]
    def diagnostics(self):
        with self._operation():
            c=self.connection
            return {'leases':c.execute('SELECT count(*) FROM leases').fetchone()[0],'operations':c.execute('SELECT count(*) FROM operations').fetchone()[0],
                    'reserved_bytes':self._reserved_bytes(),'quota_bytes':self.quota,
                    'quota_contract':'RESERVED_PAYLOAD_BYTES_NOT_TOTAL_FILESYSTEM','clock_mode':getattr(self.clock,'mode','explicit-test-port'),
                    'sqlite_version':sqlite3.sqlite_version,'automatic_gc':False,'recipient_keys_stored':False,'product_qualified':False}
