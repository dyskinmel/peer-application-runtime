"""Standard asyncio/OpenSSL TLS over an already connected, exclusively owned socket.

No listener or resolver. TLS driver owns cryptography/records. Explicit CA +
mandatory mutual certificates + SAN hostname + owner-enrolled DER pin are all
required. Local enrollment is a trust input, not evidence of its own provenance.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import socket
import ssl
import time
from .config import ALPN, TLSConfig, Limits, TransportError, positive

async def _open(sock, config, limits, cancel):
    context=config.context()
    loop=asyncio.get_running_loop()
    async def connect():
        kw=dict(ssl=context,ssl_handshake_timeout=limits.timeout,
                ssl_shutdown_timeout=limits.cleanup_timeout)
        if config.server_side:
            reader=asyncio.StreamReader(limit=limits.buffer_high_water)
            protocol=asyncio.StreamReaderProtocol(reader)
            transport,_=await loop.connect_accepted_socket(lambda:protocol,sock,**kw)
            return reader,asyncio.StreamWriter(transport,protocol,reader,loop)
        return await asyncio.open_connection(sock=sock,server_hostname=config.server_hostname,
                                             limit=limits.buffer_high_water,**kw)
    task=loop.create_task(connect())
    watcher=loop.create_task(cancel.wait()) if cancel is not None else None
    pending={task} | ({watcher} if watcher is not None else set())
    try:
        done,_=await asyncio.wait(pending,timeout=limits.timeout,return_when=asyncio.FIRST_COMPLETED)
        if watcher is not None and watcher in done:raise TransportError('CANCELLED')
        if task not in done:raise TransportError('TLS_DEADLINE')
        # Clean watcher BEFORE transferring ownership. Cancellation here still
        # disposes a just-returned writer instead of orphaning it.
        if watcher is not None:
            watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
        if cancel is not None and cancel.is_set():raise TransportError('CANCELLED')
        result=task.result()
    except BaseException:
        for item in pending:
            if not item.done():item.cancel()
        try:await asyncio.gather(*pending,return_exceptions=True)
        finally:
            if task.done() and not task.cancelled() and task.exception() is None:
                _,writer=task.result();writer.transport.abort()
                try:
                    async with asyncio.timeout(limits.cleanup_timeout):await writer.wait_closed()
                except BaseException:pass
            sock.close()
        raise
    return result

class TLSStream:
    """One reader and one writer; finite lifetime and plaintext byte counters.

    The asyncio high-water mark is flow control, NOT a hard RSS bound for native
    TLS internals. Failure/cancellation makes this stream non-reusable.
    """
    @classmethod
    async def open(cls, sock: socket.socket, config: TLSConfig, *,
                   limits: Limits | None = None, cancel: asyncio.Event | None = None):
        limits=limits if limits is not None else Limits()
        writer=None
        start=time.monotonic()
        try:
            if type(config) is not TLSConfig or type(limits) is not Limits:
                raise TransportError('TLS_CONFIG')
            if not isinstance(sock,socket.socket) or sock.type & socket.SOCK_STREAM != socket.SOCK_STREAM:
                raise TransportError('SOCKET_REQUIRED')
            if sock.family not in (socket.AF_UNIX,socket.AF_INET,socket.AF_INET6):
                raise TransportError('SOCKET_REQUIRED')
            if cancel is not None and not isinstance(cancel,asyncio.Event):raise TransportError('INVALID_CANCEL')
            if cancel is not None and cancel.is_set():raise TransportError('CANCELLED')
            sock.getpeername();sock.setblocking(False)
            reader,writer=await _open(sock,config,limits,cancel)
            info=writer.get_extra_info('ssl_object')
            if info is None or info.version()!='TLSv1.3':raise TransportError('TLS_VERSION')
            if info.selected_alpn_protocol()!=ALPN:raise TransportError('TLS_ALPN')
            certificate=info.getpeercert(binary_form=True)
            if not certificate:raise TransportError('TLS_CERTIFICATE')
            fingerprint=hashlib.sha256(certificate).hexdigest()
            if not hmac.compare_digest(fingerprint,config.peer_sha256):raise TransportError('TLS_PIN')
            if cancel is not None and cancel.is_set():raise TransportError('CANCELLED')
            if time.monotonic()>=start+limits.timeout:raise TransportError('TLS_DEADLINE')
            result=cls.__new__(cls)
            result._reader=reader;result._writer=writer;result.limits=limits
            result._loop=asyncio.get_running_loop();result._expires=start+limits.timeout
            result._closed=False;result._read_busy=False;result._write_busy=False
            result._read_left=limits.max_total_bytes;result._write_left=limits.max_total_bytes
            result._cleanup='OPEN';result._close_future=None
            result.peer_certificate_sha256=fingerprint
            result.tls_version=info.version();result.alpn=info.selected_alpn_protocol()
            result.cipher=info.cipher()[0];result._cert_not_after=ssl.cert_time_to_seconds(info.getpeercert()['notAfter'])
            result.observed_path='local-fixture' if sock.family==socket.AF_UNIX else 'direct'
            writer.transport.set_write_buffer_limits(high=limits.buffer_high_water,low=limits.buffer_high_water//2)
            return result
        except asyncio.CancelledError:
            if writer is not None:writer.transport.abort()
            sock.close();raise
        except BaseException as exc:
            if writer is not None:
                writer.transport.abort()
                try:
                    async with asyncio.timeout(limits.cleanup_timeout):await writer.wait_closed()
                except BaseException:pass
            if isinstance(sock,socket.socket):sock.close()
            if isinstance(exc,TransportError):raise
            if isinstance(exc,TimeoutError) or (isinstance(exc,ConnectionAbortedError) and 'handshake' in str(exc)):
                raise TransportError('TLS_DEADLINE') from None
            if isinstance(exc,(OSError,ValueError,ssl.SSLError,asyncio.IncompleteReadError)):
                raise TransportError('TLS_HANDSHAKE') from None
            raise

    @property
    def closed(self):return self._closed

    def remaining(self):
        return max(0.0,self._expires-time.monotonic())

    def _check(self):
        if asyncio.get_running_loop() is not self._loop:raise TransportError('WRONG_LOOP')
        if self._closed:raise TransportError('CLOSED')
        if time.time()>=self._cert_not_after:
            self.abort();raise TransportError('TLS_CERT_EXPIRED')
        if self.remaining()<=0:
            self.abort();raise TransportError('IO_DEADLINE')

    def peername(self):
        self._check();value=self._writer.get_extra_info('peername')
        return (value[0],value[1]) if isinstance(value,tuple) else value

    def io_state(self):
        return dict(closed=self._closed,read_busy=self._read_busy,write_busy=self._write_busy,
                    read_left=self._read_left,write_left=self._write_left,cleanup=self._cleanup)

    async def read_exact(self,size: int) -> bytes:
        self._check();positive(size,self.limits.chunk,'IO_LIMIT')
        if self._read_busy:raise TransportError('IO_BUSY')
        if size>self._read_left:raise TransportError('IO_LIMIT')
        self._read_left-=size;self._read_busy=True
        try:
            async with asyncio.timeout(self.remaining()):
                data=await self._reader.readexactly(size)
            self._check();return data
        except asyncio.CancelledError:self.abort();raise
        except (TimeoutError,asyncio.IncompleteReadError,OSError) as exc:
            self.abort()
            raise TransportError('IO_DEADLINE' if isinstance(exc,TimeoutError) else 'IO_TRUNCATED') from None
        finally:self._read_busy=False

    async def write(self,data: bytes | bytearray) -> None:
        self._check()
        if type(data) not in (bytes,bytearray):raise TransportError('IO_LIMIT')
        positive(len(data),self.limits.chunk,'IO_LIMIT')
        if self._write_busy:raise TransportError('IO_BUSY')
        if len(data)>self._write_left:raise TransportError('IO_LIMIT')
        snapshot=bytes(data);self._write_left-=len(snapshot);self._write_busy=True
        try:
            async with asyncio.timeout(self.remaining()):
                self._writer.write(snapshot);await self._writer.drain()
            self._check()
        except asyncio.CancelledError:self.abort();raise
        except (TimeoutError,OSError) as exc:
            self.abort()
            raise TransportError('IO_DEADLINE' if isinstance(exc,TimeoutError) else 'IO_FAILED') from None
        finally:self._write_busy=False

    def abort(self):
        self._closed=True;self._cleanup='ABORTED';self._writer.transport.abort()

    async def _finish_close(self):
        try:
            async with asyncio.timeout(self.limits.cleanup_timeout):
                await self._writer.wait_closed()
            if self._cleanup=='CLOSING':self._cleanup='GRACEFUL'
        except asyncio.CancelledError:self.abort();raise
        except (TimeoutError,OSError):self.abort()

    async def close(self):
        if asyncio.get_running_loop() is not self._loop:raise TransportError('WRONG_LOOP')
        self._closed=True
        if self._cleanup=='OPEN':self._cleanup='CLOSING';self._writer.close()
        if self._close_future is None:
            self._close_future=self._loop.create_task(self._finish_close())
        if self._close_future.cancelled():return
        try:
            await asyncio.shield(self._close_future)
        except asyncio.CancelledError:
            self.abort()
            self._close_future.cancel()
            await asyncio.gather(self._close_future,return_exceptions=True)
            raise
