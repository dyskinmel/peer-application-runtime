#!/usr/bin/env python3
"""Read-only local handoff demonstration; performs no native operation or egress."""
from __future__ import annotations
import json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from product.wp14.par_native_provider import ProviderBundle,experimental_posix_descriptor,apple_source_descriptor,local_doctor

def main():
    local=experimental_posix_descriptor(epoch='11'*16);apple=apple_source_descriptor(epoch='22'*16)
    doctor=local_doctor(ProviderBundle(local))
    print(json.dumps({'result':'PASS','scope':doctor['scope'],'defaultProvider':'BLOCKED','localProtection':local.protection,
        'appleNativeBuild':apple.native_build,'nativeBuildExecuted':False,'deviceVerified':False,
        'swiftcAvailable':shutil.which('swiftc')is not None,'rustcAvailable':shutil.which('rustc')is not None,'cargoAvailable':shutil.which('cargo')is not None,
        'egressAttempts':doctor['egressAttempts'],'productQualified':False},sort_keys=True))
    return 0
if __name__=='__main__':raise SystemExit(main())
