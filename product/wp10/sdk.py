"""Owner-injected local SDK port, not a network service or proof-bearing JSON.

The existing journal performs every signature/AEAD/authority/cursor check. This
adapter only translates immutable payloads to bounded exact JSON-safe values.
A host must dispatch on the journal's single owner thread; never use to_thread.
"""
from __future__ import annotations
import copy
import hashlib
from .events import EventError, EventJournal, decode_payload, decode, need, fixed

PROFILE = 'par-sdk-events-local-0038'

def record(value, keys):
    need(type(value) is dict and set(value) == set(keys), 'SDK_INPUT_INVALID')

def from_hex(value, size=None, max_bytes=4096):
    need(type(value) is str and 0 < len(value) <= max_bytes*2 and len(value)%2 == 0 and
         all(c in '0123456789abcdef' for c in value), 'SDK_INPUT_INVALID')
    raw=bytes.fromhex(value)
    if size is not None: fixed(raw,size)
    return raw

class EventOwnerPort:
    """One consumer session. No automatic ack, re-open, retry, cursor skip or GC."""
    def __init__(self, journal: EventJournal, consumer_id: bytes):
        fixed(consumer_id,16);journal._enter()
        self._j=journal;self._consumer=consumer_id;self._sub=None;self._closed=False;self._session=None
        context=decode(journal._context)
        self._context={'protocol':PROFILE,'appId':context[1],'spaceId':context[2].hex(),
                       'streamId':context[3].hex(),'epoch':str(context[4]),
                       'schema':dict(journal._schema),'schemaDigest':hashlib.sha256(context[5]).hexdigest(),
                       'issuer':journal._public.hex(),'consumerId':consumer_id.hex(),
                       'journalGeneration':journal._generation.hex()}
    def context(self):
        self._j._enter();return copy.deepcopy(self._context)
    def _base(self,kind):return {'kind':kind,'context':copy.deepcopy(self._context),'sessionId':self._session}
    def _enter(self,request,keys):
        self._j._enter();record(request,keys)
        need(self._sub is not None and not self._closed,'SUBSCRIPTION_CLOSED')
        need(type(request['sessionId']) is str and request['sessionId']==self._session,'SDK_SESSION_MISMATCH')
    def _cursor(self,token):
        data=self._j._untoken('events/cursor',token)
        return {'position':str(data[3]),'revision':str(data[5]),'eventId':data[4].hex() if data[4] else None,'token':token.hex()}
    def open(self,request):
        self._j._enter();record(request,['context','expectedCursor'])
        need(not self._closed and self._sub is None,'SUBSCRIPTION_BUSY')
        need(type(request['context']) is dict and request['context']==self._context,'SDK_CONTEXT_MISMATCH')
        expected=request['expectedCursor'];token=None
        if expected is not None:
            record(expected,['position','revision','eventId','token']);token=from_hex(expected['token'])
            need(expected==self._cursor(token),'CURSOR_INVALID')
        sub=self._j.subscribe(self._consumer,expected_cursor=token)
        try:
            self._sub=sub;self._session=sub._session.hex()
            return self._base('opened')|{'cursor':self._cursor(sub.cursor())}
        except BaseException:
            sub.cancel();self._sub=None;self._session=None;raise
    def poll(self,request):
        self._enter(request,['sessionId','limit','byteLimit'])
        # Cursor and batch are observed on the same owner turn. The journal
        # rechecks authority/actual bytes, including repeated pending batches.
        cursor=self._cursor(self._sub.cursor())
        batch=self._sub.poll(limit=request['limit'],byte_limit=request['byteLimit'])
        events=[]
        for e in batch.events:
            fields={}
            for name,value in decode_payload(e.payload).items():
                kind=self._j._schema[name]
                fields[name]={'kind':kind,'value':str(value) if kind in ('int64','uint64') else value.hex() if kind=='bytes' else value}
            events.append({'sequence':str(e.sequence),'eventId':e.event_id.hex(),'operationId':e.operation_id.hex(),
                           'parents':[p.hex() for p in e.parents],'payload':fields,'payloadBytes':len(e.payload)})
        return self._base('batch')|{'cursor':cursor,'events':events,'ackToken':batch.token.hex() if batch.token else None,'hasMore':batch.has_more}
    def ack(self,request):
        self._enter(request,['sessionId','token']);token=from_hex(request['token'])
        return self._base('acked')|{'cursor':self._cursor(self._sub.ack(token))}
    def cursor(self,request):
        self._enter(request,['sessionId'])
        return self._base('cursor')|{'cursor':self._cursor(self._sub.cursor())}
    def cancel(self,request):
        self._j._enter();record(request,['sessionId'])
        need(self._session is not None and request['sessionId']==self._session,'SDK_SESSION_MISMATCH')
        if not self._closed:
            self._sub.cancel();self._closed=True
        return self._base('cancelled')
