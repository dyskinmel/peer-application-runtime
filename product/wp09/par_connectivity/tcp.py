"""Native Python numeric TCP adapter and bounded socket I/O.

Raw TCP is not Noise, TLS, libp2p or a PAR authenticated stream. Instantiate only
as a trusted Connector port; a DialTarget is a value, not an unforgeable grant.
"""
from __future__ import annotations
import asyncio
import math
import socket
from .model import ConnectivityError, DialTarget
from .policy import numeric_ip


def _positive(value, maximum=16*1024*1024):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ConnectivityError('IO_BUDGET')
    return value


def _timeout(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0.001 <= value <= 60:
        raise ConnectivityError('IO_BUDGET')
    return value


class SocketConnection:
    """Owns a connected socket after successful construction. No plaintext log.

    One reader and one writer, charged before I/O; failed/cancelled operations do
    not refund bytes. The owner must not reuse this socket outside the wrapper.
    """
    def __init__(self, sock: socket.socket, *, max_chunk: int = 65536,
                 max_total_read: int = 1048576, max_total_write: int = 1048576,
                 io_timeout: float = 5.0):
        self._chunk = _positive(max_chunk)
        self._read_left = _positive(max_total_read)
        self._write_left = _positive(max_total_write)
        self._timeout = _timeout(io_timeout)
        self._loop = asyncio.get_running_loop()
        if sock.family not in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX):
            raise ConnectivityError('UNSUPPORTED_SOCKET')
        sock.setblocking(False)
        self._socket = sock
        self._closed = False
        self._read_busy = False
        self._write_busy = False
        self._pending: set[asyncio.Task] = set()
        self.observed_path = 'local-fixture' if sock.family == socket.AF_UNIX else 'direct'

    def _check(self):
        if asyncio.get_running_loop() is not self._loop:
            raise ConnectivityError('WRONG_LOOP')
        if self._closed:
            raise ConnectivityError('CLOSED')

    def peername(self):
        self._check()
        value = self._socket.getpeername()
        # For AF_UNIX this intentionally is NOT a numeric peer assertion.
        if self._socket.family == socket.AF_UNIX:
            return value
        return (value[0], value[1])

    def io_state(self) -> dict:
        return {'closed':self._closed, 'read_busy':self._read_busy, 'write_busy':self._write_busy,
                'read_left':self._read_left, 'write_left':self._write_left, 'pending':len(self._pending)}

    async def _io(self, factory):
        async def bounded():
            async with asyncio.timeout(self._timeout):
                return await factory()
        task = self._loop.create_task(bounded())
        self._pending.add(task)
        try:
            value = await task
            self._check()
            return value
        except TimeoutError:
            raise ConnectivityError('IO_DEADLINE') from None
        except asyncio.CancelledError:
            if self._closed:
                raise ConnectivityError('CLOSED') from None
            raise
        finally:
            self._pending.discard(task)

    async def read_exact(self, size: int) -> bytes:
        self._check()
        _positive(size, self._chunk)
        if self._read_busy:
            raise ConnectivityError('IO_BUSY')
        if size > self._read_left:
            raise ConnectivityError('IO_BUDGET')
        self._read_left -= size
        self._read_busy = True
        async def read():
            out = bytearray()
            while len(out) < size:
                self._check()
                chunk = await self._loop.sock_recv(self._socket, size-len(out))
                if not chunk:
                    raise ConnectivityError('EOF')
                out.extend(chunk)
            return bytes(out)
        try:
            return await self._io(read)
        finally:
            self._read_busy = False

    async def write(self, data: bytes | bytearray) -> None:
        self._check()
        if type(data) not in (bytes,bytearray):
            raise ConnectivityError('IO_BUDGET')
        _positive(len(data), self._chunk)
        if self._write_busy:
            raise ConnectivityError('IO_BUSY')
        if len(data) > self._write_left:
            raise ConnectivityError('IO_BUDGET')
        snapshot = bytes(data)
        self._write_left -= len(snapshot)
        self._write_busy = True
        try:
            await self._io(lambda: self._loop.sock_sendall(self._socket, snapshot))
        finally:
            self._write_busy = False

    async def close(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise ConnectivityError('WRONG_LOOP')
        if not self._closed:
            self._closed = True
            for task in tuple(self._pending):
                task.cancel()
            self._socket.close()
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)


class NumericTcpDialer:
    """No hostnames, redirect, proxy, fallback or resolver inside this adapter."""
    supported_schemes = frozenset({'tcp'})
    def __init__(self, *, timeout: float = 5.0):
        self._timeout = _timeout(timeout)

    async def dial(self, target: DialTarget, cancel: asyncio.Event) -> SocketConnection:
        if type(target) is not DialTarget or not isinstance(cancel, asyncio.Event):
            raise ConnectivityError('INVALID_TARGET')
        if target.scheme != 'tcp':
            raise ConnectivityError('ADAPTER_UNAVAILABLE')
        ip = numeric_ip(target.ip)
        if type(target.port) is not int or not 1 <= target.port <= 65535:
            raise ConnectivityError('INVALID_TARGET')
        if cancel.is_set():
            raise ConnectivityError('CANCELLED')
        family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        address = (str(ip), target.port) if ip.version == 4 else (str(ip), target.port, 0, 0)
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setblocking(False)
            async with asyncio.timeout(self._timeout):
                # Numeric literals make asyncio's inet_pton fast path avoid DNS.
                # server_name never replaces this tuple; TLS/Noise is a separate
                # audited adapter, not something implemented in this module.
                await asyncio.get_running_loop().sock_connect(sock, address)
            if cancel.is_set():
                raise ConnectivityError('CANCELLED')
            return SocketConnection(sock, io_timeout=self._timeout)
        except BaseException:
            sock.close()
            raise
