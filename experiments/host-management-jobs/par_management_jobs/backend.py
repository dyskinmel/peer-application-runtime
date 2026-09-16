"""Narrow adapter: explicit operations; reconciliation reads existing signed facts.

Never creates management authorization. No generic method dispatch, no mutation
in probe/validate. Only apply() invokes a mutation on the existing replay gateway.
"""
from dataclasses import dataclass
from par_upload_window import ReplaySpool,contract as w
from par_keeper.contract import authority_body
from par_keeper_upload import protocol as u
from par_keeper_upload_retire.spool import RetiringSpool
from par_recovery.transfer import read_file
from . import contract as c
E=c.E
@dataclass(frozen=True)
class Probe:
    state:str
    result:bytes|None=None
    witness:bytes|None=None

class WindowBackend:
    def __init__(self,gateway):
        if type(gateway) is not ReplaySpool:raise E('JOB_BACKEND')
        self.g=gateway;self.k=gateway.keeper;self.p=gateway.provider
    def inspect(self):
        if self.g.provider is not self.p or self.k.provider is not self.p:raise E('JOB_PROVIDER_CHANGED')
        self.g._enter();self.g._current();self.g._audit_live()
    def context(self):
        self.inspect()
        return authority_body(self.k.authority),self.g.pin(),self.g.phase,self.g.window
    def active(self):return bool(self.k._pins)
    def _row(self,b):
        seq=b[10][1]
        if seq==0:return None
        if seq>len(self.g.state[4]):raise E('JOB_TARGET_CHANGED')
        row=self.g.state[4][seq-1]
        if row[0]!=b[12]:raise E('JOB_TARGET_CHANGED')
        if b[10][3] is not None and (row[2] is None or w.digest(row[2])!=b[10][3]):raise E('JOB_TARGET_CHANGED')
        return row
    def validate(self,b,archive):
        self.inspect();g=self.g;action=b[5];cmd=b[6]
        if c.dump(authority_body(self.k.authority))!=c.dump(b[9]):raise E('STALE_AUTHORITY')
        if c.dump(g.pin())!=c.dump(b[10]) or g.phase!=b[11] or g.window!=b[12]:raise E('JOB_TARGET_CHANGED')
        if action=='open':
            q=w.check_window(self.p,cmd)
            if q[2]!=b[9] or (q[3],q[4])!=(self.k.public,g.store_id):raise E('STALE_AUTHORITY')
            previous=w.digest(g.row[4]) if g.row else None
            if g.phase not in ('EMPTY','CLEANED') or (q[5],q[7])!=(len(g.state[4])+1,previous):raise E('WINDOW_ORDER')
        elif action=='close':
            if g.phase!='OPEN':raise E('WINDOW_CLOSED')
            a=w.check_archive(self.p,archive,g.window);q=w.check_close(self.p,g.window,cmd,w.digest(archive))
            if q[2]!=b[9]:raise E('STALE_AUTHORITY')
            entries,count=g._terminal_entries()
            if [entries,count]!=[a[5],a[6]]:raise E('ARCHIVE_CHANGED')
        elif action=='compact':
            if g.phase!='CLOSED':raise E('WINDOW_NOT_CLOSED')
            q=w.check_close(self.p,g.window,g.row[2],g.row[3])
            if q[2]!=b[9]:raise E('STALE_AUTHORITY')
            g._remaining(g._archive())
        elif action=='retire':
            q=w.check_command(self.p,g.window,cmd)
            if q[3]!='retire':raise E('JOB_METHOD')
            _,_,grant=w.r.inspect_request(self.p,q[4]);t=grant[5]
            bound=read_file(g._binding(t),w.MAX_CONTROL);origin=w.check_command(self.p,g.window,bound)[4]
            g._admit(cmd);g._inner._authorize(q[4],origin)
            if g._inner._path(t,'.cbor').exists():
                _,m,_=g._inner._original(t)
                if m[5]!='active':raise E('STAGE_COMMITTED')
                if g._inner._journal_path(t).exists():
                    j,_,_=g._inner._validate_journal(t)
                    if j[5][-1]!=q[4]:raise E('RETIREMENT_REBIND_REQUIRED')
        else:raise E('JOB_METHOD')
    def apply(self,b,archive):
        if b[5]=='open':self.g.open_window(b[6])
        elif b[5]=='close':self.g.close_window(b[6],archive)
        elif b[5]=='compact':self.g.compact()
        elif b[5]=='retire':self.g.execute(b[6])
        else:raise E('JOB_METHOD')
    def probe(self,b,archive):
        self.inspect();g=self.g;a=b[5];cmd=b[6]
        if a=='open':
            q=w.check_window(self.p,cmd);seq=q[5]
            if seq>len(g.state[4]):return Probe('PENDING')
            row=g.state[4][seq-1]
            if row[0]!=cmd:raise E('JOB_TARGET_CHANGED')
            return Probe('APPLIED',c.dump({0:g.store_id,1:seq,2:w.digest(cmd),3:None}),w.digest(cmd))
        row=self._row(b)
        if row is None:raise E('JOB_TARGET_CHANGED')
        if a=='close':
            if row[1]=='OPEN':return Probe('PENDING')
            if row[2]!=cmd or row[3]!=w.digest(archive):raise E('JOB_TARGET_CHANGED')
            w.check_close(self.p,row[0],cmd,row[3])
            return Probe('APPLIED',c.dump({0:g.store_id,1:b[10][1],2:w.digest(row[0]),3:w.digest(cmd)}),w.digest(c.dump([cmd,row[3]])))
        if a=='compact':
            if row[1]=='CLOSED':return Probe('PENDING')
            if row[1]!='CLEANED':raise E('JOB_TARGET_CHANGED')
            return Probe('APPLIED',row[4],w.digest(row[4]))
        if a=='retire':
            q=w.check_command(self.p,b[12],cmd);request=q[4]
            if q[3]!='retire':raise E('JOB_METHOD')
            t=w.r.inspect_request(self.p,request)[2][5];j=None
            if row[1]=='OPEN':
                path=g._inner._journal_path(t)
                if not path.exists():return Probe('PENDING')
                j,_,_=g._inner._validate_journal(t)
            else:
                raw=read_file(g._archive_path(b[10][1]),w.MAX_ARCHIVE)
                if w.digest(raw)!=row[3]:raise E('ARCHIVE_CHANGED')
                data=w.check_archive(self.p,raw,row[0])
                entry=next((e for e in data[5] if e[0]=='live/'+t.hex()+'.retirement'),None)
                if entry is None:raise E('JOB_EVIDENCE_MISSING')
                j=w.r.verified(self.p,entry[5],'journal',self.k.public)
            if j[5][-1]!=request:raise E('JOB_TARGET_CHANGED')
            if j[6]!='TOMBSTONED':return Probe('PENDING')
            # No signatures are generated when reading historical results.
            result=RetiringSpool._status(j);result.update(unlinked_payload_bytes=j[7][2],receipt=j[9])
            return Probe('APPLIED',c.dump([[key,val] for key,val in sorted(result.items())]),w.digest(j[9]))
        raise E('JOB_METHOD')
