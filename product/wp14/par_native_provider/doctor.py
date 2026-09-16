"""Read-only local capability inspection. It never opens provider stores or dials."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,shutil
from .handoff import ProviderBundle

def _tools():return {k:shutil.which(k)is not None for k in ('swiftc','rustc','cargo')}
def local_doctor(bundle:ProviderBundle|None,*,tool_probe=None,observed_at=None):
    if bundle is None:
        return {'result':'BLOCKED','reason':'PROVIDER_NOT_SUPPLIED','scope':'LOCAL_PROVIDER_CAPABILITY_ONLY','executedNativeOperations':0,'egressAttempts':0,'telemetryEnabled':False,'productQualified':False}
    d=bundle.descriptor;probe=(tool_probe or _tools)();when=observed_at or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    return {'result':'PASS','scope':'LOCAL_PROVIDER_CAPABILITY_ONLY','observedAt':when,'freshness':'CURRENT_PROCESS',
            'providerId':d.provider_id,'providerEpochRef':hashlib.sha256(bytes.fromhex(d.epoch)).hexdigest()[:16],
            'protection':d.protection,'osProtectionProven':d.os_protection_proven,'rollbackProtectionProven':d.rollback_protection_proven,
            'nativeBuild':d.native_build,'toolchain':{k:'FOUND'if bool(probe.get(k))else'NOT_FOUND' for k in ('swiftc','rustc','cargo')},
            'capabilities':{k:v.status for k,v in d.capabilities.items()},'executedNativeOperations':0,'egressAttempts':0,
            'telemetryEnabled':False,'productQualified':False}
