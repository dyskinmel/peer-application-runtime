"""Boot-scoped elapsed time. No wall-time expiry or deletion decision."""
from dataclasses import dataclass
from pathlib import Path
import hashlib,secrets,time,uuid
from .contract import fixed,integer
@dataclass(frozen=True)
class Tick:
    boot:bytes
    ns:int
class BootClock:
    def __init__(self):
        self.mode='process-session-monotonic';self.boot=secrets.token_bytes(32);self._get=time.monotonic_ns
        try:
            raw=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            raw=str(uuid.UUID(raw));clock=time.CLOCK_BOOTTIME
            time.clock_gettime_ns(clock)
            self.boot=hashlib.sha256(('Linux/CLOCK_BOOTTIME/'+raw).encode()).digest()
            self._get=lambda:time.clock_gettime_ns(clock);self.mode='linux-boot-boottime'
        except (AttributeError,OSError,ValueError):pass
    def sample(self):
        t=Tick(self.boot,self._get());fixed(t.boot);integer(t.ns);return t
