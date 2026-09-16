"""Finite length framing over TLS; not a new message codec or crypto protocol."""
from __future__ import annotations
import struct
from .config import TransportError, positive
from .stream import TLSStream

class FramedChannel:
    def __init__(self,stream: TLSStream):
        if type(stream) is not TLSStream:raise TransportError('TLS_REQUIRED')
        self.stream=stream;self._sent=0;self._received=0;self._sending=False;self._receiving=False
    def _limit(self,limit):return positive(limit,self.stream.limits.max_frame,'FRAME_LIMIT')
    async def send(self,raw:bytes,limit:int,*,guard=None):
        limit=self._limit(limit)
        if self._sending:raise TransportError('FRAME_BUSY')
        self._sending=True
        try:
            if type(raw) is not bytes or not 1<=len(raw)<=limit or self._sent>=self.stream.limits.max_frames:
                raise TransportError('FRAME_LIMIT')
            self._sent+=1
            if guard is not None:guard()
            await self.stream.write(struct.pack('!I',len(raw)))
            for i in range(0,len(raw),self.stream.limits.chunk):
                if guard is not None:guard()
                await self.stream.write(raw[i:i+self.stream.limits.chunk])
            if guard is not None:guard()
        except BaseException:self.stream.abort();raise
        finally:self._sending=False
    async def receive(self,limit:int,*,guard=None) -> bytes:
        limit=self._limit(limit)
        if self._receiving:raise TransportError('FRAME_BUSY')
        self._receiving=True
        try:
            if self._received>=self.stream.limits.max_frames:raise TransportError('FRAME_LIMIT')
            self._received+=1
            if guard is not None:guard()
            size=struct.unpack('!I',await self.stream.read_exact(4))[0]
            if not 1<=size<=limit:raise TransportError('FRAME_LIMIT')
            parts=[]
            while size:
                if guard is not None:guard()
                n=min(size,self.stream.limits.chunk)
                parts.append(await self.stream.read_exact(n));size-=n
            if guard is not None:guard()
            return b''.join(parts)
        except BaseException:self.stream.abort();raise
        finally:self._receiving=False
