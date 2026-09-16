"""Scoped, explicit causal-data reads over a private Linux Unix socket.

A local candidate, NOT Automerge sync, a public protocol, or applied ACKs.
Only source snapshots and encrypted bytes are served. The recipient explicitly
calls SyncInbox.receive; no remote mutation, discovery, retries or auto-fetch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import re
import secrets
import selectors
import socket
import struct
import threading
import time

from par_wire.codec import encode, decode
from par_crypto import objects
from par_crypto.primitives import domain, hashed
from par_auth.membership import member_certificate
from par_store.model import u64
from par_keeper_service.transport import (
    Endpoint, private_path, socket_identity, peer_uid, frame, send, receive, remaining,
)
from par_keeper_service.errors import ServiceError
from .contracts import canonical
from .dependencies import stamp
from .inbox import RECORD_MAX

PROFILE = 'par-causal-read-local-0034'
MAX_HELLO = 8192
MAX_REQUEST = 16384
MAX_RESPONSE = 1048576
MAX_PAGE = 16
MAX_CATALOG = 128
METHODS = frozenset(('have', 'need', 'get'))
REMOTE_ERRORS = frozenset(('NOT_AUTHORIZED', 'STALE_AUTHORITY', 'STALE_VIEW',
    'DATA_INVALID', 'QUARANTINED', 'RESOURCE_BLOCKED', 'NOT_OBSERVED',
    'INVALID_REQUEST', 'REQUEST_AUTH', 'REQUEST_BINDING', 'METHOD_DENIED', 'INTERNAL'))


class ExchangeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(ok, code='INVALID_REQUEST'):
    if not ok:
        raise ExchangeError(code)


def fixed(v, n=32, code='INVALID_REQUEST'):
    require(type(v) is bytes and len(v) == n, code)


def integer(v, lo, hi, code='INVALID_REQUEST'):
    require(type(v) is int and lo <= v <= hi, code)


def keys(v, expected, code='INVALID_REQUEST'):
    require(type(v) is dict and all(type(k) is int for k in v)
            and set(v) == set(expected), code)


def scope_check(scope):
    require(type(scope) is list and len(scope) == 6)
    require(type(scope[0]) is str and re.fullmatch('[a-z0-9][a-z0-9.-]{0,127}', scope[0]))
    for i in (1, 2, 4, 5):
        fixed(scope[i])
    integer(scope[3], 1, 2**64-1)


def pack(value, limit):
    try:
        return encode(value, max_bytes=limit)
    except Exception:
        raise ExchangeError('INVALID_REQUEST') from None


def unpack(raw, limit):
    require(type(raw) is bytes and 1 <= len(raw) <= limit)
    try:
        return decode(raw, max_bytes=limit)
    except Exception:
        raise ExchangeError('INVALID_REQUEST') from None


def digest(raw):
    return hashed('causal-read/bytes', [raw])


def sign(p, seed, label, value, limit):
    raw = pack(value, limit)
    return pack({0: raw, 1: p.sign(seed, domain('causal-read/' + label, [raw]))}, limit)


def split(raw, limit):
    obj = unpack(raw, limit)
    keys(obj, (0, 1))
    fixed(obj[1], 64)
    return unpack(obj[0], limit), obj


def verify(p, public, label, obj, code):
    try:
        p.verify(public, domain('causal-read/' + label, [obj[0]]), obj[1])
    except Exception:
        raise ExchangeError(code) from None


def version(b):
    integer(b[0], 1, 1)
    require(b[1] == PROFILE)


def request_args(action, args):
    require(type(action) is str and action in METHODS, 'METHOD_DENIED')
    if action == 'have':
        keys(args, (0, 1, 2))
        if args[0] is not None:
            fixed(args[0])
        integer(args[1], 0, MAX_CATALOG)
        integer(args[2], 1, MAX_PAGE)
        require(args[1] == 0 or args[0] is not None)
    elif action == 'need':
        require(type(args) is list and 1 <= len(args) <= MAX_PAGE)
        for cid in args:
            fixed(cid)
        require(len(args) == len(set(args)))
    else:
        keys(args, (0, 1, 2))
        for k in args:
            fixed(args[k])


def make_hello(p, seed, scope, boot, nonce, deadline_ms):
    scope_check(scope)
    fixed(seed); fixed(boot); fixed(nonce)
    integer(deadline_ms, 50, 30000)
    return sign(p, seed, 'hello', {0: 1, 1: PROFILE, 2: p.sign_public(seed),
        3: scope, 4: boot, 5: nonce, 6: deadline_ms, 7: MAX_REQUEST,
        8: MAX_RESPONSE}, MAX_HELLO)


def check_hello(p, public, scope, raw):
    fixed(public); scope_check(scope)
    b, obj = split(raw, MAX_HELLO)
    keys(b, range(9)); version(b)
    scope_check(b[3])
    for k in (2, 4, 5):
        fixed(b[k])
    integer(b[6], 50, 30000)
    integer(b[7], MAX_REQUEST, MAX_REQUEST)
    integer(b[8], MAX_RESPONSE, MAX_RESPONSE)
    verify(p, public, 'hello', obj, 'HELLO_AUTH')
    require(b[2] == public, 'HELLO_AUTH')
    require(b[3] == scope, 'SCOPE_MISMATCH')
    return b


def make_request(p, seed, hello, certificate, action, args):
    request_args(action, args); fixed(seed)
    require(type(certificate) is bytes and 0 < len(certificate) <= 4096)
    return sign(p, seed, 'request', {0: 1, 1: PROFILE, 2: digest(hello),
        3: certificate, 4: action, 5: args}, MAX_REQUEST)


def check_request(source, hello, raw):
    check_hello(source.p, source.public, source.scope, hello)
    b, obj = split(raw, MAX_REQUEST)
    keys(b, range(6)); version(b); fixed(b[2])
    require(b[2] == digest(hello), 'REQUEST_BINDING')
    request_args(b[4], b[5])
    public = source.authorize(b[3])
    verify(source.p, public, 'request', obj, 'REQUEST_AUTH')
    return b[3], b[4], b[5]


def make_response(p, seed, hello, request, success, value):
    require(type(success) is bool)
    return sign(p, seed, 'response', {0: 1, 1: PROFILE, 2: digest(hello),
        3: digest(request), 4: success, 5: value}, MAX_RESPONSE)


def descriptor_check(d):
    require(type(d) is list and len(d) == 3, 'RESPONSE_SCHEMA')
    fixed(d[0], code='RESPONSE_SCHEMA'); fixed(d[1], code='RESPONSE_SCHEMA')
    integer(d[2], 1, RECORD_MAX, 'RESPONSE_SCHEMA')


def response_value(action, args, v):
    """Validate a *signed* reply too. Signature validity is not schema validity."""
    code = 'RESPONSE_SCHEMA'
    if action == 'have':
        keys(v, range(5), code); fixed(v[0], code=code)
        integer(v[1], 0, MAX_CATALOG, code); integer(v[4], 0, MAX_CATALOG, code)
        require(v[1] == args[1] and v[1] <= v[4], code)
        require(args[0] is None or v[0] == args[0], code)
        require(type(v[2]) is list and len(v[2]) == min(args[2], v[4]-v[1]), code)
        for d in v[2]:
            descriptor_check(d)
        require(v[2] == sorted(v[2]) and len({d[0] for d in v[2]}) == len(v[2])
                and len({d[1] for d in v[2]}) == len(v[2]), code)
        next_offset = v[1]+len(v[2])
        if next_offset < v[4]:
            integer(v[3], 1, MAX_CATALOG, code); require(v[3] == next_offset, code)
        else:
            require(v[3] is None, code)
    elif action == 'need':
        keys(v, (0, 1), code); fixed(v[0], code=code)
        require(type(v[1]) is list and len(v[1]) == len(args), code)
        for cid, row in zip(args, v[1]):
            require(type(row) is list and len(row) == 2 and row[0] == cid, code)
            if row[1] is not None:
                descriptor_check(row[1]); require(row[1][0] == cid, code)
    else:
        keys(v, range(6), code)
        require((v[0], v[1], v[2]) == (args[0], args[1], args[2]), code)
        require(v[5] == 'ENCRYPTED_PENDING_BYTES', code)
        require(type(v[3]) is bytes and 0 < len(v[3]) <= RECORD_MAX, code)
        require(type(v[4]) is bytes and 0 < len(v[4]) <= 4096, code)
        try:
            header = decode(decode(v[3])[0])
            require(objects.envelope_id(v[3]) == v[2] and header[12] == v[1], code)
        except ExchangeError:
            raise
        except Exception:
            raise ExchangeError(code) from None
    return v


def check_response(p, public, hello, request, raw, action, args):
    request_args(action, args)
    b, obj = split(raw, MAX_RESPONSE)
    keys(b, range(6)); version(b)
    verify(p, public, 'response', obj, 'RESPONSE_AUTH')
    require((b[2], b[3]) == (digest(hello), digest(request)), 'RESPONSE_BINDING')
    require(type(b[4]) is bool, 'RESPONSE_SCHEMA')
    if not b[4]:
        require(type(b[5]) is str and b[5] in REMOTE_ERRORS, 'RESPONSE_SCHEMA')
        raise ExchangeError('REMOTE_' + b[5])
    value = response_value(action, args, b[5])
    if action == 'get':
        # A signed descriptor is not permission to substitute another document.
        hb, _ = split(hello, MAX_HELLO)
        check_hello(p, public, hb[3], hello)
        try:
            h = decode(decode(value[3])[0])
            require([h[0], h[1], h[3], h[2], h[9]] == hb[3][:5], 'RESPONSE_SCHEMA')
        except ExchangeError:
            raise
        except Exception:
            raise ExchangeError('RESPONSE_SCHEMA') from None
    return value


class Source:
    """Read-only bounded view over an already-open authority Store + SyncInbox.

    Bootstrap/authority synchronization is external. This source deliberately
    stops on a changed known authority head rather than silently adopting it.
    """
    def __init__(self, inbox, certificate, seed):
        fixed(seed)
        self.box = inbox
        self.owner = inbox.owner
        self.p = self.owner._provider
        self._pid, self._thread = os.getpid(), threading.get_ident()
        self.certificate, self._seed = certificate, seed
        self.public = self.p.sign_public(seed)
        self.owner._enter()
        _, st = self.owner._load(inbox._space)
        self._scope = [inbox._scope_data['app'], inbox._space, inbox._doc,
            inbox._epoch, inbox._schema, st.head]
        scope_check(self._scope)
        require(self.authorize(certificate) == self.public, 'NOT_AUTHORIZED')

    @property
    def scope(self):
        return list(self._scope)

    def _enter(self):
        require(os.getpid() == self._pid and threading.get_ident() == self._thread, 'WRONG_OWNER')
        self.box._enter()

    def authorize(self, certificate):
        self._enter()
        try:
            _, state = self.owner._load(self.box._space)
            require(state.head == self._scope[5] and state.epoch == self._scope[3], 'STALE_AUTHORITY')
            require(self.owner.status(self.box._space)['state'] != 'AUTH_PERSISTENCE_UNCERTAIN', 'STALE_AUTHORITY')
            state.authorize(self.certificate, 'read')
            state.authorize(certificate, 'read')
            cert = member_certificate(self.p, state.app_id, state.membership, certificate)
            return cert[3]
        except ExchangeError:
            raise
        except Exception:
            raise ExchangeError('NOT_AUTHORIZED') from None

    def catalog(self, certificate):
        self.authorize(certificate)
        before = stamp(self.owner, self.box._space)
        try:
            records, state, _ = self.box._records()
            require(self.owner.audit()['valid'], 'DATA_INVALID')
            c = self.owner._storage.connection
            rows = c.execute('''SELECT e.envelope_id,e.encrypted_bytes,a.certificate
                FROM envelopes e JOIN commit_ledger l ON l.commit_id=e.envelope_id
                JOIN auth_commits a USING(operation_id)
                WHERE e.space_id=? AND e.object_id=? AND e.epoch=? LIMIT ?''',
                (self.box._space, self.box._doc, u64(self.box._epoch), MAX_CATALOG+1)).fetchall()
            require(len(rows) <= MAX_CATALOG, 'RESOURCE_BLOCKED')
            for eid, raw, cert in rows:
                h = self.box._outer(raw, cert, state)
                require(objects.envelope_id(raw) == eid, 'DATA_INVALID')
                if eid in records:
                    require(records[eid][:2] == (raw, cert), 'DATA_INVALID')
                records[eid] = (bytes(raw), bytes(cert), h)
            require(len(records) <= MAX_CATALOG, 'RESOURCE_BLOCKED')
            require(not self.box._conflict(records), 'QUARANTINED')
            self.authorize(certificate)
            require(before == stamp(self.owner, self.box._space), 'STALE_VIEW')
            descriptors = sorted([[r[2][12], eid, len(r[0])] for eid, r in records.items()])
            token = hashed('causal-read/snapshot', [self._scope,
                self.box._metadata['generation'], canonical(self.owner.pin(self.box._space)),
                [[d[0], d[1], d[2], digest(records[d[1]][1])] for d in descriptors]])
            return token, descriptors, records
        except ExchangeError:
            raise
        except Exception:
            raise ExchangeError('DATA_INVALID') from None

    def guard(self, certificate):
        return self.catalog(certificate)[0]

    def answer(self, certificate, action, args):
        request_args(action, args)
        token, descriptors, records = self.catalog(certificate)
        if action == 'have':
            require(args[0] is None or args[0] == token, 'STALE_VIEW')
            require(args[1] <= len(descriptors), 'INVALID_REQUEST')
            page = descriptors[args[1]:args[1]+args[2]]
            nxt = args[1]+len(page)
            return {0: token, 1: args[1], 2: page, 3: nxt if nxt < len(descriptors) else None, 4: len(descriptors)}
        if action == 'need':
            by_id = {d[0]: d for d in descriptors}
            return {0: token, 1: [[cid, by_id.get(cid)] for cid in args]}
        require(args[0] == token, 'STALE_VIEW')
        row = records.get(args[2])
        require(row is not None and row[2][12] == args[1], 'NOT_OBSERVED')
        return {0: token, 1: args[1], 2: args[2], 3: row[0], 4: row[1], 5: 'ENCRYPTED_PENDING_BYTES'}


@dataclass
class Connection:
    sock: object
    hello: bytes
    deadline: float
    phase: str = 'hello'
    output: bytes = field(default=b'', repr=False)
    incoming: bytearray = field(default_factory=bytearray, repr=False)
    sent: int = 0
    want: int = 4
    certificate: bytes | None = field(default=None, repr=False)
    guard: bytes | None = None


class Server:
    """One owner, bounded selectors, one explicit read per fresh signed challenge.

    Deadlines bound socket processing, not synchronous disk/native execution.
    All state/byte guards remain live. No worker pool or auto-resumption.
    """
    def __init__(self, source, path, *, max_connections=4, deadline_ms=5000, send_chunk=65536):
        integer(max_connections, 1, 8); integer(deadline_ms, 50, 30000); integer(send_chunk, 1, 65536)
        source._enter()
        self.source = source
        self._pid, self._thread = os.getpid(), threading.get_ident()
        self.deadline_ms, self.max_connections, self.send_chunk = deadline_ms, max_connections, send_chunk
        self.boot = secrets.token_bytes(32)
        self.closed = False; self.connections = {}; self.endpoint = None
        self.selector = selectors.DefaultSelector()
        self.counts = dict(accepted=0, completed=0, rejected=0, dropped=0, expired=0, overloaded=0, changed=0)
        try:
            self.endpoint = Endpoint(path, max_connections)
            self.selector.register(self.endpoint.socket, selectors.EVENT_READ, None)
        except BaseException:
            self.close(); raise

    def _owner(self):
        require((os.getpid(), threading.get_ident()) == (self._pid, self._thread), 'WRONG_OWNER')
        require(not self.closed, 'CLOSED')

    def _drop(self, c, complete=False):
        fd = c.sock.fileno()
        try: self.selector.unregister(c.sock)
        except (KeyError, ValueError): pass
        c.sock.close(); self.connections.pop(fd, None)
        c.output = b''; c.incoming.clear()
        self.counts['completed' if complete else 'dropped'] += 1

    def _accept(self):
        for _ in range(self.max_connections+1):
            try: s, _ = self.endpoint.socket.accept()
            except BlockingIOError: return
            if len(self.connections) >= self.max_connections:
                self.counts['overloaded'] += 1; s.close(); continue
            try:
                peer_uid(s); s.setblocking(False)
                hello = make_hello(self.source.p, self.source._seed, self.source.scope,
                    self.boot, secrets.token_bytes(32), self.deadline_ms)
                c = Connection(s, hello, time.monotonic()+self.deadline_ms/1000,
                               output=frame(hello, MAX_HELLO))
                self.selector.register(s, selectors.EVENT_WRITE, c)
                self.connections[s.fileno()] = c; self.counts['accepted'] += 1
            except Exception:
                s.close(); self.counts['rejected'] += 1

    def _read(self, c):
        b = c.sock.recv(c.want-len(c.incoming))
        if not b: self._drop(c); return
        c.incoming.extend(b)
        if len(c.incoming) != c.want: return
        if c.want == 4:
            n = struct.unpack('>I', c.incoming)[0]
            require(0 < n <= MAX_REQUEST, 'INVALID_REQUEST')
            c.want = 4+n; return
        raw = bytes(c.incoming[4:])
        try:
            cert, action, args = check_request(self.source, c.hello, raw)
            value = self.source.answer(cert, action, args)
            c.certificate, c.guard = cert, value[0]
            response = make_response(self.source.p, self.source._seed, c.hello, raw, True, value)
        except Exception as e:
            code = getattr(e, 'code', 'INTERNAL')
            if code not in REMOTE_ERRORS: code = 'INTERNAL'
            c.guard = None
            self.counts['rejected'] += 1
            response = make_response(self.source.p, self.source._seed, c.hello, raw, False, code)
        c.output = frame(response, MAX_RESPONSE)
        c.sent = 0; c.incoming.clear(); c.phase = 'response'
        self.selector.modify(c.sock, selectors.EVENT_WRITE, c)

    def _write(self, c):
        if c.phase == 'response' and c.guard is not None:
            try:
                require(c.guard == self.source.guard(c.certificate), 'STALE_VIEW')
            except Exception:
                self.counts['changed'] += 1; self._drop(c); return
        n = c.sock.send(memoryview(c.output)[c.sent:c.sent+self.send_chunk])
        if not n: self._drop(c); return
        c.sent += n
        if c.sent < len(c.output): return
        if c.phase == 'response': self._drop(c, True); return
        c.output = b''; c.sent = 0; c.phase = 'request'
        self.selector.modify(c.sock, selectors.EVENT_READ, c)

    def poll(self, timeout=.05):
        self._owner()
        require(type(timeout) in (int, float) and 0 <= timeout <= 1)
        now = time.monotonic()
        for c in list(self.connections.values()):
            if c.deadline <= now: self.counts['expired'] += 1; self._drop(c)
        if self.connections:
            timeout = min(timeout, max(0, min(c.deadline for c in self.connections.values())-time.monotonic()))
        for key, mask in self.selector.select(timeout):
            if key.data is None: self._accept(); continue
            c = key.data
            if c.sock.fileno() < 0: continue
            if time.monotonic() >= c.deadline:
                self.counts['expired'] += 1; self._drop(c); continue
            try:
                if mask & selectors.EVENT_READ: self._read(c)
                elif mask & selectors.EVENT_WRITE: self._write(c)
            except BlockingIOError: continue
            except (OSError, ExchangeError, ServiceError):
                if c.sock.fileno() >= 0: self._drop(c)

    def close(self):
        require((os.getpid(), threading.get_ident()) == (self._pid, self._thread), 'WRONG_OWNER')
        if self.closed: return
        for c in list(self.connections.values()): self._drop(c)
        if self.endpoint: self.endpoint.close()
        self.selector.close(); self.closed = True


class Client:
    """Pinned one-shot reads. Network errors are never retried implicitly."""
    def __init__(self, path, provider, public, scope, certificate, seed, *, timeout=5):
        fixed(public); fixed(seed); scope_check(scope)
        require(type(certificate) is bytes and 0 < len(certificate) <= 4096)
        require(type(timeout) in (int, float) and .05 <= timeout <= 30)
        self.path = private_path(path); self.p = provider; self.public = public
        self._scope = list(scope); self.certificate = certificate; self._seed = seed
        self.timeout = timeout

    def call(self, action, args):
        request_args(action, args)
        # An owned canonical copy prevents mutation while a socket call is in flight.
        args = unpack(pack(args, MAX_REQUEST), MAX_REQUEST)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic()+self.timeout; sent = False
        try:
            identity = socket_identity(self.path)
            s.settimeout(remaining(deadline)); s.connect(str(self.path)); peer_uid(s)
            require(socket_identity(self.path) == identity, 'SOCKET_IDENTITY')
            hello = receive(s, MAX_HELLO, deadline)
            hb = check_hello(self.p, self.public, self._scope, hello)
            deadline = min(deadline, time.monotonic()+hb[6]/1000)
            request = make_request(self.p, self._seed, hello, self.certificate, action, args)
            sent = True; send(s, request, MAX_REQUEST, deadline)
            reply = receive(s, MAX_RESPONSE, deadline)
            return check_response(self.p, self.public, hello, request, reply, action, args)
        except ServiceError as e:
            raise ExchangeError('OUTCOME_UNKNOWN' if sent and e.code in ('DEADLINE','DISCONNECTED') else e.code) from None
        except OSError:
            raise ExchangeError('OUTCOME_UNKNOWN' if sent else 'CONNECTION_UNAVAILABLE') from None
        finally:
            s.close()

    def have(self, *, snapshot=None, offset=0, limit=16):
        return self.call('have', {0: snapshot, 1: offset, 2: limit})

    def need(self, inner_ids):
        return self.call('need', inner_ids)

    def fetch(self, snapshot, descriptor):
        descriptor_check(descriptor)
        value = self.call('get', {0: snapshot, 1: descriptor[0], 2: descriptor[1]})
        require(len(value[3]) == descriptor[2], 'RESPONSE_SCHEMA')
        return value[3], value[4]


def transfer_one(client, inbox, snapshot, descriptor):
    """Explicit single object pull. Failed later requests never roll back earlier bytes.

    Local receive independently verifies sender signature, ciphertext and current
    authorization. The result is PENDING_BYTES, not an application commit.
    """
    scope = inbox._scope_data
    require(client._scope[:5] == [scope['app'], inbox._space, inbox._doc,
                                 inbox._epoch, inbox._schema], 'SCOPE_MISMATCH')
    raw, cert = client.fetch(snapshot, descriptor)
    return inbox.receive(raw, cert)
