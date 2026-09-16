"""Explicit finite TLS reads and existing SyncInbox persistence.

Progress is a local observation, never an application commit. No auto retry,
no remote ACK, no new nonce or plaintext ledger. ReadSession is consumed once.
"""
import asyncio,copy,json,re
from product.wp04 import exchange as x
from product.wp04.inbox import InboxError
from product.wp04.contracts import canonical
from product.wp09.par_secure_transport import ReadSession
from .plan import FetchPlan,PROFILE
from .persistence import FetchError,require,save_new,load_pinned

def error_code(exc):
    code=getattr(exc,'code',None)
    return code if type(code)is str and re.fullmatch('[A-Z_]{1,80}',code)else'FETCH_FAILED'

class FetchClient:
    def __init__(self,plan:FetchPlan,source:x.Source,current_generation):
        require(type(plan)is FetchPlan and type(source)is x.Source and callable(current_generation),'CLIENT_INPUT')
        self._plan=plan;self._source=source;self._generation=current_generation
        self._busy=False;self._uncertain=False;self._state='NOT_RECONCILED';self._reason=None
        self._items=[{'envelopeId':d[1].hex(),'state':'NOT_OBSERVED','candidateState':None}for d in plan.descriptors]
        self._guard()
    @property
    def plan(self):return self._plan
    def _guard(self):
        p=self._plan;s=self._source
        require(tuple(s.scope)==p.scope,'PLAN_SCOPE')
        require(s.box._metadata['generation']==p.inbox_generation,'INBOX_GENERATION')
        current=self._generation()
        require(type(current)is int and current==p.binding.generation,'STALE_GENERATION')
        try:s.authorize(p.binding.certificate)
        except Exception as e:raise FetchError(error_code(e))from None
    def _enter(self):
        require(not self._busy,'FETCH_BUSY');require(not self._uncertain,'REOPEN_REQUIRED');self._guard()
    def progress(self):
        return {'profile':PROFILE,'planDigest':self.plan.digest,'state':self._state,'reason':self._reason,
                'stored':sum(r['state']=='INBOX_STORED'for r in self._items),'total':len(self._items),
                'items':copy.deepcopy(self._items),'applied':False,'localCommitted':False,
                'replicated':False,'acknowledged':False,'observationOnly':True}
    def _summary(self):
        self._reason=None
        if any(r['candidateState']=='QUARANTINED'for r in self._items):self._state='REVIEW_REQUIRED'
        elif all(r['state']=='INBOX_STORED'for r in self._items):self._state='COMPLETE_PENDING'
        else:self._state='PARTIAL_PENDING'
    def _stop(self,exc,index=None):
        self._reason=error_code(exc)
        if self._reason=='INBOX_OUTCOME_UNKNOWN':
            self._uncertain=True;self._state='RECONCILE_REQUIRED'
            if index is not None:self._items[index]['state']='OUTCOME_UNKNOWN'
        else:
            self._state='STOPPED'
            if index is not None and self._items[index]['state']=='REQUESTING':self._items[index]['state']='FETCH_FAILED'
    def _mark_stored(self,i):
        self._items[i]['state']='INBOX_STORED'
        self._guard()
        self._items[i]['candidateState']=self._source.box.inspect(self.plan.descriptors[i][1])['state']
    def _reconcile(self,expected_pin=None):
        self._guard();box=self._source.box
        try:
            if expected_pin is not None:box._check_pin(expected_pin)
            records,_,_=box._records()
            for i,d in enumerate(self.plan.descriptors):
                row=records.get(d[1])
                if row is None:
                    self._items[i].update(state='NOT_OBSERVED',candidateState=None);continue
                raw,certificate,header=row
                require(header[12]==d[0]and len(raw)==d[2],'DESCRIPTOR_MISMATCH')
                # Explicit local re-sync. A checkpoint flag alone never promotes a record.
                self._guard();box.receive(raw,certificate);self._mark_stored(i)
            self._guard();self._summary();return self.progress()
        except Exception as e:self._stop(e);raise FetchError(error_code(e))from None
    def reconcile(self,*,expected_pin=None):
        self._enter();self._busy=True
        try:return self._reconcile(expected_pin)
        finally:self._busy=False
    def save_checkpoint(self,path):
        self._enter();self._busy=True
        try:
            self._reconcile();pin=self._source.box.pin();self._guard()
            return save_new(path,canonical({'version':1,'profile':PROFILE,'planDigest':self.plan.digest,'inboxPin':pin}))
        finally:self._busy=False
    def restore_checkpoint(self,path,*,expected_sha256):
        self._enter();self._busy=True
        try:
            raw=load_pinned(path,expected_sha256);v=json.loads(raw)
            require(type(v)is dict and set(v)=={'version','profile','planDigest','inboxPin'}and canonical(v)==raw,'CHECKPOINT_SCHEMA')
            require(type(v['version'])is int and v['version']==1 and v['profile']==PROFILE and v['planDigest']==self.plan.digest,'CHECKPOINT_PLAN')
            return self._reconcile(v['inboxPin'])
        except FetchError:raise
        except Exception as e:raise FetchError(error_code(e))from None
        finally:self._busy=False
    def _cancel(self,cancel):
        require(cancel is None or isinstance(cancel,asyncio.Event),'INVALID_CANCEL')
        task=asyncio.current_task()
        if task is not None and task.cancelling():raise asyncio.CancelledError
        if cancel is not None and cancel.is_set():raise FetchError('CANCELLED')
    def _index(self,index):
        require(type(index)is int and 0<=index<len(self.plan.descriptors),'INVALID_INDEX')
    async def _fetch(self,index,session,cancel):
        require(type(session)is ReadSession,'SESSION_REQUIRED')
        try:
            self._index(index);self._guard();self._cancel(cancel)
            require(session.source is self._source and session.binding==self.plan.binding,'SESSION_BINDING')
            session._authority_guard()
            require(self._state!='REVIEW_REQUIRED','QUARANTINED')
            if self._items[index]['state']=='INBOX_STORED':
                self._reconcile()
            else:
                d=self.plan.descriptors[index];args={0:self.plan.snapshot,1:d[0],2:d[1]}
                self._items[index]['state']='REQUESTING';self._state='FETCHING'
                reply=await session.request('get',args,cancel=cancel)
                self._guard();self._cancel(cancel)
                # Defense in depth: signed/schema-checked read data is independently
                # pinned to descriptor and reverified by the existing Inbox receiver.
                value=x.unpack(x.pack(reply,x.MAX_RESPONSE),x.MAX_RESPONSE)
                x.response_value('get',args,value)
                require(len(value[3])==d[2],'DESCRIPTOR_MISMATCH')
                self._source.box.receive(value[3],value[4]);self._mark_stored(index)
                self._guard();self._cancel(cancel);self._summary()
        except asyncio.CancelledError:
            self._stop(FetchError('CANCELLED'),index if type(index)is int and 0<=index<len(self._items)else None);raise
        except Exception as e:
            self._stop(e,index if type(index)is int and 0<=index<len(self._items)else None)
            raise FetchError(error_code(e))from None
        finally:
            try:await session.stream.close()
            except asyncio.CancelledError:
                if not self._uncertain:self._stop(FetchError('CANCELLED'))
                raise
            except Exception as e:
                if not self._uncertain:self._stop(e)
                raise FetchError(error_code(e))from None
        # Cleanup can yield; keep the same guard at the final result boundary.
        try:self._guard();self._cancel(cancel)
        except asyncio.CancelledError:self._stop(FetchError('CANCELLED'));raise
        except Exception as e:self._stop(e);raise FetchError(error_code(e))from None
        return self.progress()
    async def fetch_one(self,index,session,*,cancel=None):
        # On BUSY ownership is not transferred; caller keeps its unused session.
        require(not self._busy,'FETCH_BUSY');self._busy=True
        try:
            if self._uncertain:
                if type(session)is ReadSession:await session.stream.close()
                raise FetchError('REOPEN_REQUIRED')
            return await self._fetch(index,session,cancel)
        finally:self._busy=False
    async def _open(self,factory,index,cancel):
        task=asyncio.ensure_future(factory(index))
        watcher=asyncio.create_task(cancel.wait())if cancel is not None else None
        pending={task}|({watcher}if watcher is not None else set())
        try:
            await asyncio.wait(pending,return_when=asyncio.FIRST_COMPLETED)
            self._cancel(cancel)
            if watcher is not None:
                watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
            self._cancel(cancel);self._guard()
            return task.result()
        except BaseException:
            for t in pending:
                if not t.done():t.cancel()
            # A trusted factory must cooperate with cancellation. If it returns
            # a session while cancellation is being delivered, reap that session.
            try:await asyncio.gather(*pending,return_exceptions=True)
            finally:
                if task.done()and not task.cancelled()and task.exception()is None:
                    result=task.result()
                    if type(result)is ReadSession:await result.stream.close()
            raise
    async def execute(self,open_session,*,indices=None,cancel=None,timeout=30.0):
        self._enter();require(callable(open_session),'SESSION_FACTORY')
        require(type(timeout)in(int,float)and 0.05<=timeout<=120,'INVALID_TIMEOUT')
        require(indices is None or type(indices)in(tuple,list),'INVALID_INDEX')
        selected=tuple(range(len(self._items)))if indices is None else tuple(indices)
        for i in selected:self._index(i)
        require(len(set(selected))==len(selected),'DUPLICATE_INDEX')
        self._busy=True
        try:
            deadline=asyncio.get_running_loop().time()+timeout
            def budget():
                require(asyncio.get_running_loop().time()<deadline,'FETCH_DEADLINE')
            self._cancel(cancel);self._reconcile();require(self._state!='REVIEW_REQUIRED','QUARANTINED');budget()
            async with asyncio.timeout_at(deadline):
                for i in selected:
                    self._guard();self._cancel(cancel);budget()
                    if self._items[i]['state']=='INBOX_STORED':continue
                    # Trusted cooperative factory owns resources until return.
                    session=await self._open(open_session,i,cancel)
                    await self._fetch(i,session,cancel)
                    budget()
            self._guard();self._cancel(cancel);budget();return self.progress()
        except asyncio.CancelledError:self._stop(FetchError('CANCELLED'));raise
        except Exception as e:
            if isinstance(e,TimeoutError):e=FetchError('FETCH_DEADLINE')
            if not self._uncertain:self._stop(e)
            raise FetchError(error_code(e))from None
        finally:self._busy=False
