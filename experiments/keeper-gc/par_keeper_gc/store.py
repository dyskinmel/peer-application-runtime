"""Explicit, resumable local GC for cooperative single-writer Keeper instances.

No scheduler, expiry-triggered deletion, shared dedup, network reader or raw FD
lending. A marked lease is already released. Audit metadata is never collected.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import hashlib,os,sqlite3,stat,threading
from par_keeper.store import Keeper,APPLICATION_ID,_schema,_expected_schema
from par_keeper.contract import (load,dump,split,authority_body,authority_from,inventory,
    fixed,signed)
from par_keeper.errors import KeeperError as E
from par_store.fs import safe,sync_dir
from par_recovery.transfer import read_file
from par_recovery.contract import object_id
from .contract import *

DDL=Path(__file__).resolve().parents[1]/'schema.sql'
TABLES=Path(__file__).resolve().parents[1]/'tables.sql'
MAX_JOBS=256

class Reader:
    """Instance-bound opaque reader. No usable fd/path survives close or GC."""
    def __init__(self,keeper,lease,oid,cap,call,token):
        self._k=keeper;self._lease=lease;self._oid=oid;self._cap=cap;self._call=call;self._token=token
    def read(self):
        if self._k._closed:raise E('CLOSED')
        if self._token not in self._k._pins:raise E('PIN_CLOSED')
        return self._k.fetch(self._lease,self._oid,self._cap,self._call)

class KeeperGC(Keeper):
    DDL_PATH=DDL
    SCHEMA_VERSION=2
    def __init__(self,root,provider,signing_seed,authority,*,migrate_v1=False,**kw):
        self._pins={}
        if type(migrate_v1) is not bool:raise E('CONTRACT_SCHEMA')
        # This precheck only selects a path; the old Keeper rechecks while locked.
        db=safe(Path(root)/'keeper.sqlite')
        if migrate_v1 and db.exists():
            c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
            try:version=c.execute('PRAGMA user_version').fetchone()[0]
            finally:c.close()
            if version==1:
                with Keeper(root,provider,signing_seed,authority,**kw) as old:
                    def upgrade():
                        for sql in TABLES.read_text().split(';'):
                            if sql.strip():old.connection.execute(sql)
                        old.connection.execute('UPDATE metadata SET profile=?',(hashlib.sha256(DDL.read_bytes()).digest(),))
                        old.connection.execute('PRAGMA user_version=2');old._emit('gc_migrate.recorded')
                    old._transaction('gc_migrate',upgrade)
        super().__init__(root,provider,signing_seed,authority,**kw)
    def close(self):
        self._pins.clear()
        super().close()
    def _reserved_bytes(self):
        gross=super()._reserved_bytes()
        credit=self.connection.execute("SELECT coalesce(sum(credit),0) FROM gc_jobs WHERE phase='done'").fetchone()[0]
        if not 0<=credit<=gross:raise E('CORRUPT_GC')
        return gross-credit
    def _lease_limit_count(self):
        return self.connection.execute("SELECT count(*) FROM leases WHERE id NOT IN (SELECT lease FROM gc_jobs WHERE phase='done')").fetchone()[0]
    def _job(self,lid):return self.connection.execute('SELECT * FROM gc_jobs WHERE lease=?',(lid,)).fetchone()
    def _release_op(self,lid,rid=None):
        rows=self.connection.execute("SELECT * FROM operations WHERE lease=? AND action='release' ORDER BY id",(lid,)).fetchall()
        if not rows:raise E('NOT_RELEASED')
        op=next((o for o in rows if o['id']==rid),None) if rid is not None else rows[0]
        if op is None:raise E('GC_SCOPE')
        self._validate_response(op,self._lease(lid));return op
    def gc_target(self,lid):
        """Trusted-host diagnostic only. Not an unauthenticated network endpoint."""
        with self._operation():
            row=self._lease(lid)
            if row['state']!='released':raise E('NOT_RELEASED')
            return {'generation':row['generation'],'release_id':self._release_op(lid)['id'],'index':self._pin(row).index_id}
    def _scope(self,lid,cap,raw,*,historical=False):
        row=self._lease(lid)
        auth=authority_from(split(cap)[0][2]) if historical else self.authority
        req,cb=verify_request(self.provider,auth,self.public,cap,raw)
        if not historical and self.connection.execute('SELECT authority FROM metadata').fetchone()[0]!=dump(authority_body(self.authority)):raise E('STALE_AUTHORITY')
        if req[5]!=lid or req[6]!=row['generation'] or cb[5]!=self._pin(row).index_id:raise E('GC_SCOPE')
        if req[4]!=row['owner']:raise E('LEASE_OWNER')
        if row['state']!='released':raise E('NOT_RELEASED')
        self._release_op(lid,req[7]);return row,req,cb
    def _unpinned(self,lid):
        if lid in self._pins.values():raise E('PINNED')
    @contextmanager
    def reader(self,lid,oid,capability,call):
        """Lease-wide short-lived pin; every read still checks current permissions."""
        with self._operation():
            _,_,row=self._authorized(capability,call,'get',lid,oid);self._serving(row)
            if oid not in {d[0] for d in self._info(row)[0]}:raise E('OBJECT_SCOPE')
            token=object();self._pins[token]=lid
            reader=Reader(self,lid,oid,capability,call,token)
        try:yield reader
        finally:self._pins.pop(token,None)
    def _directory(self,lid):
        return safe(self.root/'objects'/lid.hex())
    def _scan(self,row,allowed=None):
        """Bounded exact file-set validation. Never recurse and never accept links."""
        path=self._directory(row['id'])
        expected={d[0]:(d[1],d[2]) for d in self._info(row)[0]}
        if allowed is not None:expected={oid:expected[oid] for oid in allowed}
        found={}
        if path.exists():
            if not path.is_dir():raise E('GC_UNSAFE_FILE')
            with os.scandir(path) as entries:
                for entry in entries:
                    if len(found)>1024:raise E('GC_UNKNOWN_FILE')
                    try:oid=bytes.fromhex(entry.name)
                    except ValueError:raise E('GC_UNKNOWN_FILE') from None
                    if len(entry.name)!=64 or oid.hex()!=entry.name or oid not in expected:raise E('GC_UNKNOWN_FILE')
                    st=entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise E('GC_UNSAFE_FILE')
                    kind,n=expected[oid];raw=read_file(path/entry.name)
                    if len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
                    found[oid]=(st.st_dev,st.st_ino,n)
        return found
    def _intent_body(self,row,req,raw,present):
        ds,_,total=self._info(row)
        return {0:1,1:PROFILE,2:self.public,3:row['id'],4:request_id(raw),5:self._pin(row).index_id,
                6:row['generation'],7:req[7],8:authority_body(self.authority),9:[list(x) for x in ds],
                10:sorted(present),11:total,12:len(row['index_raw']),13:sum(x[2] for x in present.values())}
    def _check_job(self,job):
        try:
            row,req,cap=self._scope(job['lease'],job['capability'],job['request'],historical=True)
            b=verify_intent(self.provider,job['intent'],self.public)
            ds,_,total=self._info(row);expected={x[0]:x for x in ds}
            if job['id']!=operation_id(req):raise E('CORRUPT_GC')
            if b[10]!=sorted(set(b[10])) or not set(b[10])<=set(expected):raise E('CORRUPT_GC')
            present={oid:(0,0,expected[oid][2]) for oid in b[10]}
            v=self._intent_body(row,req,job['request'],present);v[8]=cap[2]
            if b!=v:raise E('CORRUPT_GC')
            recorded={r[0] for r in self.connection.execute('SELECT oid FROM stored_objects WHERE lease=?',(row['id'],))}
            if job['phase']=='marked':
                if job['result'] is not None or job['credit']!=0 or not recorded<=set(b[10]):raise E('CORRUPT_GC')
            else:
                verify_result(self.provider,job['result'],self.public,job['request'])
                v,_=split(job['result'])
                if v!=result_body(self.public,job['request'],b) or job['credit']!=total or recorded:raise E('CORRUPT_GC')
                if self._directory(job['lease']).exists():raise E('CORRUPT_GC')
            return b
        except Exception:raise E('CORRUPT_GC') from None
    def _validate_database(self):
        super()._validate_database()
        jobs=self.connection.execute('SELECT * FROM gc_jobs').fetchall()
        if len(jobs)>MAX_JOBS:raise E('CORRUPT_GC')
        for job in jobs:
            self._check_job(job)
            if job['phase']=='done' and self._directory(job['lease']).exists():raise E('CORRUPT_GC')
    def _status(self,row):
        result=super()._status(row);job=self._job(row['id'])
        if job is not None:
            self._check_job(job)
            result['state']='RECLAIMED' if job['phase']=='done' else 'GC_PENDING'
            result['reserved_bytes']=row['charge']-job['credit']
            result['gc_pending']=job['phase']=='marked'
        result['reader_pins']=sum(v==row['id'] for v in self._pins.values())
        return result
    def _mark(self,lid,capability,raw):
        row,req,cap=self._scope(lid,capability,raw);self._unpinned(lid)
        old=self._job(lid)
        if old is not None:
            if old['request']!=raw or old['capability']!=capability:raise E('GC_CONFLICT')
            self._check_job(old);return old
        self._validate_database()
        present=self._scan(row)
        recorded={r[0] for r in self.connection.execute('SELECT oid FROM stored_objects WHERE lease=?',(lid,))}
        if not recorded<=set(present):raise E('GC_OBJECT_MISSING')
        body=self._intent_body(row,req,raw,present)
        intent=sign_intent(self.provider,self._seed,body);jid=operation_id(req)
        def apply():
            self._scope(lid,capability,raw);self._unpinned(lid)
            if self.connection.execute('SELECT count(*) FROM gc_jobs').fetchone()[0]>=MAX_JOBS:raise E('GC_LIMIT')
            if self.connection.execute('SELECT 1 FROM gc_jobs WHERE id=?',(jid,)).fetchone():raise E('GC_CONFLICT')
            if self._scan(row)!=present:raise E('GC_FILE_CHANGED')
            self.connection.execute("INSERT INTO gc_jobs VALUES(?,?,?,?,?,'marked',NULL,0)",(lid,jid,raw,capability,intent))
            self._emit('gc_mark.recorded')
        self._transaction('gc_mark',apply)
        return self._job(lid)
    def mark(self,lid,capability,raw):
        with self._operation():
            job=self._mark(lid,capability,raw)
            return {'job_id':job['id'],'state':'RECLAIMED' if job['phase']=='done' else 'GC_PENDING','quota_refunded':job['credit']}
    def collect(self,lid,capability,raw):
        with self._operation():
            job=self._mark(lid,capability,raw);body=self._check_job(job)
            if job['phase']=='done':return job['result']
            row,_,_=self._scope(lid,capability,raw);self._unpinned(lid)
            present=self._scan(row,body[10]);path=self._directory(lid)
            if path.exists():
                fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    for oid,identity in sorted(present.items()):
                        self._scope(lid,capability,raw);self._unpinned(lid)
                        self._emit('gc_sweep.before_unlink')
                        st=os.stat(oid.hex(),dir_fd=fd,follow_symlinks=False)
                        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or (st.st_dev,st.st_ino,st.st_size)!=identity:raise E('GC_FILE_CHANGED')
                        os.unlink(oid.hex(),dir_fd=fd);self._emit('gc_sweep.after_unlink')
                        os.fsync(fd);self._emit('gc_sweep.after_dirsync')
                    if os.listdir(fd):raise E('GC_UNKNOWN_FILE')
                    os.fsync(fd)
                finally:os.close(fd)
                os.rmdir(path);self._emit('gc_sweep.after_rmdir')
            sync_dir(self.root/'objects');self._emit('gc_sweep.parent_synced')
            response=signed(self.provider,self._seed,'gc-result-sign',result_body(self.public,raw,body))
            def finish():
                self._scope(lid,capability,raw);self._unpinned(lid)
                self._check_job(self._job(lid))
                if path.exists() or path.is_symlink():raise E('GC_FILE_CHANGED')
                self.connection.execute('DELETE FROM stored_objects WHERE lease=?',(lid,))
                self.connection.execute("UPDATE gc_jobs SET phase='done',result=?,credit=? WHERE lease=? AND phase='marked'",(response,body[11],lid))
                self._emit('gc_finish.recorded');return response
            return self._transaction('gc_finish',finish)
    def reserve(self,*args,**kwargs):
        # Credits must still match both the signed history and physical namespace.
        with self._operation():self._validate_database()
        return super().reserve(*args,**kwargs)
    def diagnostics(self):
        with self._operation():self._validate_database()
        out=super().diagnostics()
        out.update({'gc_profile':PROFILE,'reader_pins':len(self._pins),'automatic_gc':False,
            'gc_pending':self.connection.execute("SELECT count(*) FROM gc_jobs WHERE phase='marked'").fetchone()[0],
            'gc_done':self.connection.execute("SELECT count(*) FROM gc_jobs WHERE phase='done'").fetchone()[0],
            'active_lease_slots':self._lease_limit_count(),'tombstone_limit':MAX_JOBS,
            'metadata_retained':True,'secure_erasure_proven':False,'shared_dedup':False})
        return out
