"""Exact frame boundaries and incremental input; never opens sockets itself."""
from __future__ import annotations
import math
import time
from . import codec
from .schema import validate_frame
from .errors import WireError

MAX_FRAME = 1_048_576


def encode_frame(frame) -> bytes:
    validate_frame(frame)
    body=codec.encode(frame)
    return len(body).to_bytes(4,'big')+body


def decode_frame(wire: bytes):
    if type(wire) is not bytes:raise TypeError('frame requires bytes')
    if len(wire)<4:raise WireError('TRUNCATED')
    n=int.from_bytes(wire[:4],'big')
    if not 1<=n<=MAX_FRAME or len(wire)!=4+n:raise WireError('LENGTH')
    value=codec.decode(wire[4:]);validate_frame(value)
    return value


class FrameReader:
    """Single-stream decoder with fixed partial-frame deadline and bounded buffer.

    A feed call is transactional from the caller's perspective: on error it returns
    no frames and permanently closes. Feed chunks and output batches are locally
    bounded; the caller must provide transport backpressure, no bytes are discarded
    while claiming success. Expiry must be polled by feed(b'', now=...) on idle input.
    """
    def __init__(self, *, timeout: float=30, max_frames_per_feed: int=64):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise ValueError('invalid timeout')
        if type(max_frames_per_feed) is not int or not 1<=max_frames_per_feed<=1024:
            raise ValueError('invalid frame batch budget')
        self.timeout=timeout;self.max_frames=max_frames_per_feed
        self._buffer=bytearray();self._length=None;self._started=None;self._last=None;self._closed=False

    @property
    def buffered_bytes(self):return len(self._buffer)

    def _close(self):
        self._closed=True;self._buffer.clear();self._length=None;self._started=None

    def feed(self, data: bytes, *, now: float|None=None) -> list:
        if self._closed:raise WireError('CLOSED')
        if type(data) is not bytes:raise TypeError('feed requires bytes')
        now=time.monotonic() if now is None else now
        try:
            if type(now) not in (float,int) or not math.isfinite(now) or (self._last is not None and now<self._last):
                raise WireError('CLOCK')
            self._last=now
            if self._started is not None and now-self._started>=self.timeout:raise WireError('TIMEOUT')
            if len(data)>MAX_FRAME+4:raise WireError('RESOURCE_LIMIT')
            pos=0;out=[]
            while pos<len(data):
                if len(out)>=self.max_frames:raise WireError('RESOURCE_LIMIT')
                if self._started is None:self._started=now
                target=4 if self._length is None else self._length
                count=min(target-len(self._buffer),len(data)-pos)
                self._buffer.extend(data[pos:pos+count]);pos+=count
                if len(self._buffer)<target:break
                if self._length is None:
                    n=int.from_bytes(self._buffer,'big')
                    if not 1<=n<=MAX_FRAME:raise WireError('LENGTH')
                    self._buffer.clear();self._length=n
                else:
                    value=codec.decode(bytes(self._buffer));validate_frame(value);out.append(value)
                    self._buffer.clear();self._length=None;self._started=None
            return out
        except WireError:
            self._close();raise

    def finish(self) -> None:
        if self._closed:raise WireError('CLOSED')
        incomplete=bool(self._buffer) or self._length is not None
        self._close()
        if incomplete:raise WireError('TRUNCATED')
