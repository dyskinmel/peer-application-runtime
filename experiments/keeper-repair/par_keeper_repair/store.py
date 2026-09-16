"""Resumable content-addressed repairs; no rekey, lease extension or auto repair.

The synchronous adapter accepts an exact bounded replacement byte map. It never
fetches URLs or creates authorizations. A repair intent reserves independent
staging budget before I/O. Historical result retrieval is not a fresh health check.
"""
from pathlib import Path
import hashlib,sqlite3
from par_keeper_gc.store import KeeperGC
from par_keeper.contract import (split,dump,signed,authority_body,authority_from,
    fixed,inventory,check_receipt)
from par_keeper.errors import KeeperError as E
from par_recovery.contract import object_id
from par_recovery.transfer import mkdir
from par_store.fs import safe
from .contract import *
from .filesystem import job_path,check_stage,clean_stage,probe,replace_object

DDL=Path(__file__).resolve().parents[1]/'schema.sql'
TABLES=Path(__file__).resolve().parents[1]/'tables.sql'

class KeeperRepair(KeeperGC):
    DDL_PATH=DDL
    SCHEMA_VERSION=3
    def __init__(self,root,provider,signing_seed,authority,*,migrate_v2=False,**kw):
        if type(migrate_v2) is not bool:raise E('CONTRACT_SCHEMA')
        if 'migrate_v1' in kw:raise E('MIGRATE_V2_ONLY')
        db=safe(Path(root)/'keeper.sqlite')
        if migrate_v2 and db.exists():
            c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
            try:version=c.execute('PRAGMA user_version').fetchone()[0]
            finally:c.close()
            if version==2:
                with KeeperGC(root,provider,signing_seed,authority,**kw) as old:
                    def upgrade():
                        for sql in TABLES.read_text().split(';'):
                            if sql.strip():old.connection.execute(sql)
                        old.connection.execute('UPDATE metadata SET profile=?',(hashlib.sha256(DDL.read_bytes()).digest(),))
                        old.connection.execute('PRAGMA user_version=3');old._emit('repair_migrate.recorded')
                    old._transaction('repair_migrate',upgrade)
        super().__init__(root,provider,signing_seed,authority,**kw)
        try:mkdir(self.root/'repair-staging');self._validate_database()
        except BaseException:self.close();raise
    def _repair_job(self,jid):
        fixed(jid);row=self.connection.execute('SELECT * FROM repair_jobs WHERE id=?',(jid,)).fetchone()
        if row is None:raise E('REPAIR_UNKNOWN')
        return row
    def _pending(self,lid=None):
        sql="SELECT * FROM repair_jobs WHERE phase IN ('prepared','aborting')"
        return self.connection.execute(sql+(' AND lease=?' if lid is not None else ''),(lid,) if lid is not None else ()).fetchall()
    def _repair_scope(self,lid,cap,raw,*,historical=False):
        row=self._lease(lid);auth=authority_from(split(cap)[0][2]) if historical else self.authority
        req,cb=verify_request(self.provider,auth,self.public,cap,raw)
        if (req[5],req[7])!=(lid,self._pin(row).index_id):raise E('REPAIR_SCOPE')
        if req[4]!=row['owner']:raise E('LEASE_OWNER')
        if not historical:
            self._current_authority();self._serving(row)
            if row['state']!='sealed':raise E('NOT_SEALED')
            if req[6]!=row['generation']:raise E('STALE_REPAIR')
            self._unpinned(lid)
            if self._job(lid) is not None:raise E('REPAIR_GC_CONFLICT')
        elif req[6]>row['generation']:raise E('CORRUPT_REPAIR')
        ds,_,_=self._info(row);expected={d[0]:d for d in ds}
        if not set(req[8])<=set(expected):raise E('OBJECT_SCOPE')
        return row,req,cb,[list(expected[x]) for x in req[8]]
    def _current_authority(self):
        if self.connection.execute('SELECT authority FROM metadata').fetchone()[0]!=dump(authority_body(self.authority)):raise E('STALE_AUTHORITY')
    def _old_receipt(self,row,generation):
        found=[]
        for op in self.connection.execute("SELECT response FROM operations WHERE lease=? AND action IN ('seal','renew')",(row['id'],)):
            b=check_receipt(self.provider,op[0],self.public,row['index_raw'],self._pin(row),row['id'])
            if b[17]==generation:found.append(op[0])
        if len(found)!=1:raise E('CORRUPT_REPAIR')
        return hashlib.sha256(found[0]).digest()
    def _intent(self,row,req,cap,raw,ds,tick):
        _,iid,_=self._info(row)
        return {0:1,1:PROFILE,2:self.public,3:job_id(req),4:request_id(raw),5:row['id'],6:self._pin(row).index_id,
                7:iid,8:req[6],9:self._old_receipt(row,req[6]),10:cap[2],11:ds,12:sum(d[2] for d in ds),13:tick.boot,14:tick.ns}
    def _check_repair_job(self,job):
        try:
            row,req,cap,ds=self._repair_scope(job['lease'],job['capability'],job['request'],historical=True)
            b=signed_body(self.provider,job['intent'],self.public,'repair-intent-sign',range(15))
            fixed(b[13]);integer(b[14]);integer(b[12],1,MAX_STAGING)
            from par_keeper.clock import Tick
            if b!=self._intent(row,req,cap,job['request'],ds,Tick(b[13],b[14])) or job['id']!=job_id(req):raise E('CORRUPT_REPAIR')
            if job['phase']=='done':
                v=verify_result(self.provider,job['result'],self.public,expected_request=job['request']);body,_=split(job['result'])
                if body[9]!=b[9] or job['cancel_request'] is not None or job['cancel_capability'] is not None:raise E('CORRUPT_REPAIR')
            elif job['phase'] in ('aborting','aborted'):
                a,cap2=verify_cancel(self.provider,authority_from(split(job['cancel_capability'])[0][2]),self.public,job['cancel_capability'],job['cancel_request'])
                if (a[5],a[6],a[4],cap2[5])!=(row['id'],job['id'],row['owner'],self._pin(row).index_id):raise E('CORRUPT_REPAIR')
                if job['phase']=='aborted':
                    result=signed_body(self.provider,job['result'],self.public,'repair-cancel-result-sign',range(9))
                    if result!=self._cancel_body(job):raise E('CORRUPT_REPAIR')
                elif job['result'] is not None:raise E('CORRUPT_REPAIR')
            elif job['phase']!='prepared' or job['result'] is not None or job['cancel_request'] is not None or job['cancel_capability'] is not None:raise E('CORRUPT_REPAIR')
            check_stage(self.root,job['id'],req[8])
            if job['phase'] in ('done','aborted') and job_path(self.root,job['id']).exists():raise E('CORRUPT_REPAIR')
            return b
        except Exception:raise E('CORRUPT_REPAIR') from None
    def _validate_database(self):
        super()._validate_database()
        jobs=self.connection.execute('SELECT * FROM repair_jobs').fetchall()
        if len(jobs)>MAX_JOBS:raise E('CORRUPT_REPAIR')
        budget=0;leases=set()
        for j in jobs:
            b=self._check_repair_job(j)
            if j['phase'] in ('prepared','aborting'):
                if j['lease'] in leases:raise E('CORRUPT_REPAIR')
                leases.add(j['lease']);budget+=b[12]
                if self._job(j['lease']) is not None:raise E('CORRUPT_REPAIR')
        if budget>MAX_STAGING:raise E('CORRUPT_REPAIR')
        stage=safe(self.root/'repair-staging')
        if stage.exists():
            if not stage.is_dir():raise E('REPAIR_UNSAFE_FILE')
            allowed={j['id'].hex() for j in jobs if j['phase'] in ('prepared','aborting')}
            for p in stage.iterdir():
                safe(p)
                if p.name not in allowed or not p.is_dir():raise E('REPAIR_UNKNOWN_FILE')
    def _mark_repair(self,lid,cap,raw):
        row,req,cb,ds=self._repair_scope(lid,cap,raw)
        old=self.connection.execute('SELECT * FROM repair_jobs WHERE id=?',(job_id(req),)).fetchone()
        if old is not None:
            if old['request']!=raw or old['capability']!=cap:raise E('REPAIR_CONFLICT')
            self._check_repair_job(old)
            if old['phase'] in ('aborting','aborted'):raise E('REPAIR_ABORTED')
            return old
        self._validate_database()
        for oid,kind,n in ds:probe(self.object_path(lid,oid),kind,n,oid)
        b=self._intent(row,req,cb,raw,ds,self._sample())
        if b[12]>MAX_STAGING:raise E('REPAIR_STAGING_CAPACITY')
        intent=signed(self.provider,self._seed,'repair-intent-sign',b)
        def apply():
            self._repair_scope(lid,cap,raw)
            if self._pending(lid):raise E('REPAIR_PENDING')
            if self.connection.execute('SELECT count(*) FROM repair_jobs').fetchone()[0]>=MAX_JOBS:raise E('REPAIR_LIMIT')
            if sum(self._check_repair_job(j)[12] for j in self._pending())+b[12]>MAX_STAGING:raise E('REPAIR_STAGING_CAPACITY')
            self.connection.execute("INSERT INTO repair_jobs VALUES(?,?,?,?,?,'prepared',NULL,NULL,NULL)",(b[3],lid,raw,cap,intent));self._emit('repair_mark.recorded')
        self._transaction('repair_mark',apply);return self._repair_job(b[3])
    def mark_repair(self,lid,capability,request):
        with self._operation():
            j=self._mark_repair(lid,capability,request)
            return {'job_id':j['id'],'state':j['phase'],'retention_extended':False}
    def repair(self,lid,replacements,capability,request):
        with self._operation():
            row,req,cap,ds=self._repair_scope(lid,capability,request)
            if type(replacements) is not dict or set(replacements)!=set(req[8]):raise E('REPAIR_OBJECT_SET')
            # Freeze caller input before callbacks or I/O.
            rawmap={}
            for oid,kind,n in ds:
                raw=replacements[oid]
                if type(raw) is not bytes or len(raw)!=n or object_id(kind,raw)!=oid:raise E('OBJECT_HASH')
                rawmap[oid]=raw
            job=self._mark_repair(lid,capability,request);b=self._check_repair_job(job)
            if job['phase']=='done':return job['result']  # historical observation, not fresh proof
            check_stage(self.root,job['id'],req[8])
            def recheck():self._repair_scope(lid,capability,request)
            for oid,kind,n in ds:
                recheck();replace_object(self.root,job['id'],lid,oid,kind,n,rawmap[oid],self._emit,recheck)
            clean_stage(self.root,job['id'],req[8],self._emit)
            def finish():
                row,_,_,_=self._repair_scope(lid,capability,request);self._check_repair_job(self._repair_job(job['id']))
                for oid,kind,n in ds:
                    if probe(self.object_path(lid,oid),kind,n,oid)[0]!='valid':raise E('OBJECT_HASH')
                    self.connection.execute('INSERT OR IGNORE INTO stored_objects VALUES(?,?)',(lid,oid))
                have,bad=self._bytes(row);all_bytes=not bad and len(have)==len(self._info(row)[0]);tick=self._sample()
                body={0:1,1:PROFILE,2:self.public,3:job['id'],4:request_id(request),5:lid,6:b[8],7:b[6],8:req[8],9:b[9],10:tick.boot,11:tick.ns,12:all_bytes,13:'TARGET_BYTES_VERIFIED',14:False,15:False}
                result=signed(self.provider,self._seed,'repair-observation-sign',body)
                self.connection.execute("UPDATE repair_jobs SET phase='done',result=? WHERE id=? AND phase='prepared'",(result,job['id']));self._emit('repair_finish.recorded');return result
            return self._transaction('repair_finish',finish)
    def _cancel_scope(self,lid,cap,raw):
        req,cb=verify_cancel(self.provider,self.authority,self.public,cap,raw);self._current_authority();row=self._lease(lid)
        if req[5]!=lid or cb[5]!=self._pin(row).index_id:raise E('REPAIR_SCOPE')
        if req[4]!=row['owner']:raise E('LEASE_OWNER')
        j=self._repair_job(req[6])
        if j['lease']!=lid:raise E('REPAIR_SCOPE')
        return j,req
    def _cancel_body(self,job):
        return {0:1,1:PROFILE,2:self.public,3:job['id'],4:job['lease'],5:hashed('keeper-local/repair-cancel-id',[job['cancel_request']]),6:'REPAIR_ABORTED',7:False,8:False}
    def cancel_repair(self,lid,capability,request):
        with self._operation():
            job,req=self._cancel_scope(lid,capability,request);self._check_repair_job(job)
            if job['phase']=='done':raise E('REPAIR_ALREADY_DONE')
            if job['cancel_request'] is not None and (job['cancel_request']!=request or job['cancel_capability']!=capability):raise E('REPAIR_CONFLICT')
            if job['phase']=='aborted':return job['result']
            if job['phase']=='prepared':
                def mark():
                    self._cancel_scope(lid,capability,request)
                    self.connection.execute("UPDATE repair_jobs SET phase='aborting',cancel_request=?,cancel_capability=? WHERE id=?",(request,capability,job['id']));self._emit('repair_abort_mark.recorded')
                self._transaction('repair_abort_mark',mark)
            job=self._repair_job(job['id']);b=self._check_repair_job(job)
            clean_stage(self.root,job['id'],[d[0] for d in b[11]],self._emit)
            def finish():
                current,_=self._cancel_scope(lid,capability,request);self._check_repair_job(current)
                result=signed(self.provider,self._seed,'repair-cancel-result-sign',self._cancel_body(current))
                self.connection.execute("UPDATE repair_jobs SET phase='aborted',result=? WHERE id=?",(result,job['id']));self._emit('repair_abort_finish.recorded');return result
            return self._transaction('repair_abort_finish',finish)
    def _mark(self,lid,cap,raw):
        if self._pending(lid):raise E('REPAIR_PENDING')
        return super()._mark(lid,cap,raw)
    def renew(self,lid,*args,**kw):
        with self._operation():
            if self._pending(lid):raise E('REPAIR_PENDING')
        return super().renew(lid,*args,**kw)
    def diagnostics(self):
        out=super().diagnostics()
        out.update({'repair_profile':PROFILE,'repair_jobs':self.connection.execute('SELECT count(*) FROM repair_jobs').fetchone()[0],
            'repair_pending':len(self._pending()),'repair_staging_reserved_bytes':sum(self._check_repair_job(j)[12] for j in self._pending()),
            'repair_staging_limit_bytes':MAX_STAGING,'repair_audit_limit':MAX_JOBS,'automatic_repair':False})
        return out
