"""Public signed-history replay. No key persistence, latest-head oracle or auth journal.

The expected digest/head MUST come from the caller's separate trusted record,
not from the supplied export itself. A fresh process starts with no active keys.
Exports reveal public membership metadata and need private local handling.
"""
from par_wire.codec import decode
from par_wire.errors import WireError
from par_crypto.primitives import hashed
from .common import canonical,blob,fixed
from .chain import AuthorityState
from .errors import AuthError
MAX_EXPORT=900000

def export_public_replay(state):
    state._thread_check()
    events=[[code,list(value) if code==2 else value] for code,value in state._events]
    return canonical({0:1,1:state.app_id,2:state.space_id,3:state._genesis,4:events},limit=MAX_EXPORT)

def restore_public_replay(provider,expected_app,expected_space,expected_head,expected_digest,raw,*,minimum_sequence):
    fixed(expected_head,32);fixed(expected_digest,32);blob(raw,MAX_EXPORT)
    if type(minimum_sequence) is not int or not 0<=minimum_sequence<2**64:raise AuthError('REPLAY_SCHEMA')
    if hashed('auth-local/replay',[raw])!=expected_digest:raise AuthError('REPLAY_DIGEST')
    try:v=decode(raw,max_bytes=MAX_EXPORT)
    except WireError:raise AuthError('REPLAY_SCHEMA') from None
    if type(v) is not dict or any(type(k) is not int for k in v) or set(v)!=set(range(5)) or type(v[0]) is not int or v[0]!=1:raise AuthError('REPLAY_SCHEMA')
    if v[1]!=expected_app or v[2]!=expected_space:raise AuthError('TRUST_ANCHOR')
    if type(v[4]) is not list or len(v[4])>2049:raise AuthError('RESOURCE_BLOCKED')
    result=AuthorityState(provider,expected_app,expected_space,v[3])
    for position,item in enumerate(v[4]):
        if type(item) is not list or len(item)!=2 or type(item[0]) is not int or item[0] not in (1,2):raise AuthError('REPLAY_SCHEMA')
        try:
            if item[0]==1:result.observe(item[1])
            else:result.provide_membership(item[1])
        except AuthError as e:
            # Correctly signed terminal faults stay terminal, never become successful authority state.
            if e.code not in ('CONTROL_FORK','CONTENT_MEMBERSHIP_CHANGED','NO_CONTENT_RECIPIENT') or position!=len(v[4])-1:raise
    if result.head!=expected_head or result.sequence<minimum_sequence:raise AuthError('REPLAY_STALE')
    return result
