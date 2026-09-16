"""Coalescing snapshots and volatile presence. Neither is a durable event log.

No background worker is spawned. A trusted owner explicitly dispatches a single
callback at a time. Closing cannot interrupt a callback already in progress.
Bytes/integers are immutable; returned objects carry no secret key handles.
"""
from __future__ import annotations
import os
import threading
import time
from dataclasses import dataclass

class SubscriptionError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

def need(ok,code='INVALID_INPUT'):
    if not ok:raise SubscriptionError(code)

def fixed(value,n):need(type(value) is bytes and len(value)==n)
def uint(value):need(type(value) is int and 0<=value<2**64)

class Owned:
    def __init__(self):self._owner=(os.getpid(),threading.get_ident())
    def check(self):need(self._owner==(os.getpid(),threading.get_ident()),'WRONG_OWNER')

@dataclass(frozen=True)
class Snapshot:
    revision:int
    value:bytes

class LatestSnapshot(Owned):
    durable=False
    capacity=1
    def __init__(self,revision,value,callback):
        super().__init__();need(callable(callback));self._closed=False;self._dispatching=False;self._callback=callback
        self._last=None;self._pending=None;self.publish(revision,value)
    @property
    def pending_count(self):self.check();return int(self._pending is not None)
    def publish(self,revision,value):
        self.check();need(not self._closed,'CLOSED');uint(revision)
        need(type(value) is bytes and len(value)<=65536,'RESOURCE_LIMIT')
        item=Snapshot(revision,value)
        if self._last is not None:
            need(revision>=self._last.revision,'STALE_SNAPSHOT')
            if revision==self._last.revision:
                need(value==self._last.value,'SNAPSHOT_CONFLICT');return
        self._last=item;self._pending=item
    def dispatch(self):
        self.check();need(not self._dispatching,'REENTRANT_DISPATCH')
        if self._closed:return 'CLOSED'
        if self._pending is None:return 'IDLE'
        item=self._pending;self._pending=None;self._dispatching=True
        try:self._callback(item);return 'DELIVERED'
        except Exception:return 'CALLBACK_FAILED'
        finally:self._dispatching=False
    def close(self):
        self.check();self._closed=True;self._pending=None;self._last=None;self._callback=None

@dataclass(frozen=True)
class PresenceView:
    state:str
    value:bytes|None=None
    sequence:int|None=None

class PresenceHints(Owned):
    """Sessions are activated by the trusted transport after authentication.

    Incoming hints cannot choose a new session. TTL uses the receiving process's
    monotonic clock. Expiry is unknown recent state, never proof of being offline.
    """
    durable=False
    def __init__(self,*,clock=time.monotonic_ns,max_peers=128):
        super().__init__();need(callable(clock) and type(max_peers) is int and 1<=max_peers<=1024)
        self._clock=clock;self._limit=max_peers;self._peers={};self._now=None;self._uncertain=False
    def _time(self):
        self.check();need(not self._uncertain,'CLOCK_UNCERTAIN')
        try:n=self._clock();need(type(n) is int and n>=0,'CLOCK_UNCERTAIN')
        except Exception:self._uncertain=True;raise SubscriptionError('CLOCK_UNCERTAIN') from None
        if self._now is not None and n<self._now:
            self._uncertain=True;self._peers.clear();raise SubscriptionError('CLOCK_UNCERTAIN')
        self._now=n;return n
    def activate(self,peer,session):
        self.check();fixed(peer,32);fixed(session,16);self._time()
        need(peer in self._peers or len(self._peers)<self._limit,'RESOURCE_LIMIT')
        old=self._peers.get(peer)
        if old is None or old[0]!=session:self._peers[peer]=(session,None,None,0,0)
    def update(self,peer,session,sequence,value,*,ttl_ns):
        self.check();fixed(peer,32);fixed(session,16);uint(sequence)
        need(type(value) is bytes and len(value)<=4096,'RESOURCE_LIMIT')
        need(type(ttl_ns) is int and 1<=ttl_ns<=60000000000)
        now=self._time();old=self._peers.get(peer);need(old is not None and old[0]==session,'SESSION_MISMATCH')
        if old[1] is not None:
            need(sequence>=old[1],'STALE_HINT')
            if sequence==old[1]:need(value==old[2] and ttl_ns==old[4],'HINT_CONFLICT');return
        self._peers[peer]=(session,sequence,value,now+ttl_ns,ttl_ns)
    def get(self,peer):
        self.check();fixed(peer,32);now=self._time();row=self._peers.get(peer)
        if row is None or row[1] is None or now>=row[3]:return PresenceView('RECENT_STATE_UNKNOWN')
        return PresenceView('RECENT_HINT',row[2],row[1])
    def forget(self,peer):self.check();fixed(peer,32);self._peers.pop(peer,None)
