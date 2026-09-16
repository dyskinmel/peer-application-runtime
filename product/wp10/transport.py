"""Private connected-descriptor bridge for EventHost; no listening endpoint.

The embedding owner authenticates/selects the peer and supplies a connected
AF_UNIX stream plus a fixed consumer ID. Descriptor possession is the transport
capability. JSON is not a signature, and plaintext event values cross this local
IPC channel. It must never be attached to a public or unauthenticated socket.
"""
from __future__ import annotations
import asyncio
import json
import socket
import struct
from .events import EventError, need
from .host import EventHost, PROTOCOL, MAX_REQUEST, MAX_RESPONSE, OPERATIONS, plain


def decode_frame(raw: bytes):
    def pairs(items):
        out = {}
        for k, v in items:
            need(k not in out, 'HOST_FRAME_INVALID'); out[k] = v
        return out
    def bad(_): raise EventError('HOST_FRAME_INVALID')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=bad, parse_constant=bad)
        return plain(value)[0]
    except (ValueError, UnicodeError, RecursionError): raise EventError('HOST_FRAME_INVALID') from None


def _ordinal(value):
    need(type(value) is str and 0 < len(value) <= 20 and value.isascii() and value.isdecimal(), 'HOST_FRAME_INVALID')
    n = int(value)
    need(str(n) == value and 0 < n < 2**64, 'HOST_FRAME_INVALID')
    return n


async def serve_connected(host: EventHost, sock: socket.socket, consumer_id: bytes,
                          *, read_timeout=5.0, write_timeout=5.0):
    """Serve a capability handed in by the trusted owner on its asyncio thread.

    Two in-flight operations and a three-frame output queue per connection.
    Aborts only cancel queued/waiting futures: committed effects remain committed.
    EOF/timeout drops the session and all volatile buffers, never ACKs a delivery.
    The caller owns EventHost/Journal, this function owns and closes ``sock``.
    """
    await _serve_service(host, sock, lambda: host.attach(consumer_id),
                         protocol=PROTOCOL, operations=OPERATIONS,
                         read_timeout=read_timeout, write_timeout=write_timeout)


async def _serve_service(host, sock, attach, *, protocol, operations,
                         read_timeout, write_timeout):
    """Internal bounded framing shared by separately selected owner services.

    Service/protocol/operations/attach are chosen by trusted wrappers, never JSON.
    """
    host._enter()
    need(isinstance(sock, socket.socket) and sock.family == socket.AF_UNIX and
         sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM, 'HOST_SOCKET_INVALID')
    sock.getpeername()  # Must already be connected; no listener/start_server here.
    for t in (read_timeout, write_timeout):
        need(type(t) in (int, float) and .01 <= t <= 60, 'HOST_OPTIONS_INVALID')
    loop = asyncio.get_running_loop(); sock.setblocking(False)
    channel = attach()
    output: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)
    active: dict[str, asyncio.Future] = {}
    stopped = False
    owner_task = asyncio.current_task()
    last_id = 0

    def frame(value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        need(0 < len(data) <= MAX_RESPONSE, 'HOST_RESPONSE_LIMIT')
        return struct.pack('!I', len(data)) + data

    def stop():
        if not stopped and owner_task is not None: owner_task.cancel()

    def enqueue(value):
        try: output.put_nowait(frame(value))
        except Exception: stop()

    async def exactly(n):
        out = bytearray()
        while len(out) < n:
            raw = await loop.sock_recv(sock, min(n - len(out), 65536))
            if not raw: raise EOFError()
            out.extend(raw)
        return bytes(out)

    async def read():
        # One absolute deadline covers header plus body, not per-byte resets.
        async with asyncio.timeout(read_timeout):
            n = struct.unpack('!I', await exactly(4))[0]
            need(0 < n <= MAX_REQUEST, 'HOST_FRAME_LIMIT')
            return decode_frame(await exactly(n))

    async def writer():
        try:
            while True:
                data = await output.get()
                async with asyncio.timeout(write_timeout):
                    await loop.sock_sendall(sock, data)
                output.task_done()
        except (OSError, TimeoutError): stop()

    def completion(rid, operation, future):
        active.pop(rid, None)
        if stopped:
            if not future.cancelled(): future.exception()
            return
        base = {'v': 1, 'id': rid, 'op': operation}
        if future.cancelled(): enqueue(base | {'error': 'HOST_REQUEST_CANCELLED'}); return
        e = future.exception()
        if e is not None:
            code = e.code if isinstance(e, EventError) else 'HOST_OPERATION_FAILED'
            enqueue(base | {'error': code})
        else: enqueue(base | {'value': future.result()})

    enqueue({'v': 1, 'kind': 'hello', 'protocol': protocol,
             'hostId': host.stats()['hostId'], 'context': host.context(channel),
             'maxRequest': MAX_REQUEST, 'maxResponse': MAX_RESPONSE})
    async def owner_shutdown():
        await host.wait_closed(); stop()

    send_task = loop.create_task(writer())
    shutdown_task = loop.create_task(owner_shutdown())
    try:
        while True:
            request = await read()
            need(type(request) is dict and type(request.get('v')) is int and request['v'] == 1, 'HOST_FRAME_INVALID')
            if set(request) == {'v', 'cancel'}:
                n = _ordinal(request['cancel']); need(n <= last_id, 'HOST_FRAME_INVALID')
                pending = active.get(request['cancel'])
                if pending is not None: pending.cancel()
                continue
            need(set(request) == {'v', 'id', 'op', 'args'}, 'HOST_FRAME_INVALID')
            n = _ordinal(request['id']); need(n > last_id, 'HOST_REPLAY_REJECTED')
            last_id = n
            rid, op = request['id'], request['op']
            need(type(op) is str and op in operations and len(active) < 2, 'HOST_CHANNEL_BUSY')
            try: future = host.request(channel, op, request['args'])
            except EventError as e:
                enqueue({'v': 1, 'id': rid, 'op': op, 'error': e.code}); continue
            active[rid] = future
            future.add_done_callback(lambda f, rid=rid, op=op: completion(rid, op, f))
    except (EOFError, OSError, TimeoutError, EventError, asyncio.CancelledError):
        pass
    finally:
        stopped = True
        for f in list(active.values()): f.cancel()
        host.detach(channel)
        send_task.cancel(); shutdown_task.cancel()
        await asyncio.gather(send_task, shutdown_task, return_exceptions=True)
        sock.close()
