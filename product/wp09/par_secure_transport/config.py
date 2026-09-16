"""Explicit, immutable TLS candidate configuration. No PKI provisioner."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math
import re
import ssl

ALPN = 'par-causal-read-exp/1'

class TransportError(ValueError):
    """A finite reason without hostnames, certificates, keys or raw exceptions."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def positive(value, maximum, code='INVALID_LIMIT'):
    if type(value) is not int or not 1 <= value <= maximum:
        raise TransportError(code)
    return value

def seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not .001 <= value <= 60:
        raise TransportError('INVALID_LIMIT')
    return float(value)

def pin(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise TransportError('INVALID_PIN')
    return value

@dataclass(frozen=True, slots=True)
class Limits:
    # One absolute lifetime from handshake start, not renewed by progress.
    timeout: float = 5.0
    cleanup_timeout: float = .25
    max_frame: int = 1048576
    max_total_bytes: int = 4194304
    max_frames: int = 4
    chunk: int = 65536
    buffer_high_water: int = 65536
    def __post_init__(self):
        seconds(self.timeout); seconds(self.cleanup_timeout)
        if type(self.chunk) is not int or self.chunk < 4: raise TransportError('INVALID_LIMIT')
        for name, maximum in [('max_frame',1048576),('max_total_bytes',16777216),
                              ('max_frames',16),('chunk',65536),('buffer_high_water',65536)]:
            positive(getattr(self,name),maximum)

@dataclass(frozen=True, slots=True)
class TLSConfig:
    server_side: bool
    ca_file: str | Path
    cert_file: str | Path
    key_file: str | Path
    peer_sha256: str
    server_hostname: str | None = None
    def __post_init__(self):
        if type(self.server_side) is not bool:
            raise TransportError('TLS_CONFIG')
        pin(self.peer_sha256)
        for name in ('ca_file','cert_file','key_file'):
            value=getattr(self,name)
            if not isinstance(value,(str,Path)) or not str(value) or '\x00' in str(value):
                raise TransportError('TLS_CONFIG')
            object.__setattr__(self,name,Path(value))
        name=self.server_hostname
        if self.server_side:
            if name is not None:raise TransportError('TLS_CONFIG')
        elif type(name) is not str or len(name)>253 or any(
            re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',x) is None
            for x in name.split('.')):
            raise TransportError('TLS_HOSTNAME')

    def context(self) -> ssl.SSLContext:
        try:
            # Do not call create_default_context: ambient SSLKEYLOGFILE and
            # system roots must not silently join this explicit trust profile.
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if self.server_side else ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version=ssl.TLSVersion.TLSv1_3
            context.maximum_version=ssl.TLSVersion.TLSv1_3
            context.verify_mode=ssl.CERT_REQUIRED
            context.check_hostname=not self.server_side
            context.hostname_checks_common_name=False
            context.verify_flags |= ssl.VERIFY_X509_STRICT
            context.set_alpn_protocols([ALPN])
            context.keylog_filename=None
            context.load_verify_locations(cafile=str(self.ca_file))
            context.load_cert_chain(str(self.cert_file),str(self.key_file))
            if self.server_side:context.num_tickets=0
            return context
        except (OSError,ValueError,ssl.SSLError):
            raise TransportError('TLS_CONFIG') from None
