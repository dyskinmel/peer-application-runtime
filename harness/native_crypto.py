"""Measure a pinned native image in a child process. No PATH/soname fallback.

A matching hash is local evidence, not upstream authenticity or qualification.
Trusted workspace required; this does not sandbox malicious local policy edits.
"""
from __future__ import annotations
import json,re,subprocess,sys
from pathlib import Path
from .common import read_json,safe_path,file_hash,clean_env,HarnessError

PROBE = '''import ctypes,_ctypes,json,hashlib,sys
from pathlib import Path
p=Path(sys.argv[1]);lib=ctypes.CDLL(str(p));lib.sodium_version_string.restype=ctypes.c_char_p
lib.sodium_version_string.argtypes=[]
x=Path(_ctypes.__file__).resolve()
print(json.dumps({'version':lib.sodium_version_string().decode('ascii'),
 'ctypes_extension_path':str(x),'ctypes_extension_sha256':hashlib.sha256(x.read_bytes()).hexdigest()}))
'''

def measure(root: Path) -> dict:
    base={'available':False,'security_qualified':False,'dependency_coverage':'PINNED_IMAGE_AND_CTYPES_EXTENSION_ONLY','auto_fallback':False}
    try:
        path=safe_path(root,'policy/crypto-provider.json')
        if not path.is_file():return base|{'reason':'PIN_MISSING'}
        if path.stat().st_size>65536:return base|{'reason':'PIN_INVALID'}
        pin=read_json(path);base['pin_sha256']=file_hash(path)
        if type(pin) is not dict or type(pin.get('schema_version')) is not int or pin['schema_version']!=1:return base|{'reason':'PIN_INVALID'}
        sha=pin.get('sha256');version=pin.get('version');candidates=pin.get('candidate_paths')
        if type(sha) is not str or not re.fullmatch('[0-9a-f]{64}',sha) or type(version) is not str or not re.fullmatch(r'\d+\.\d+\.\d+',version):return base|{'reason':'PIN_INVALID'}
        if type(candidates) is not list or not 1<=len(candidates)<=8:return base|{'reason':'PIN_INVALID'}
        for candidate in candidates:
            if type(candidate) is not str or not Path(candidate).is_absolute() or '..' in Path(candidate).parts:return base|{'reason':'PIN_INVALID'}
        for candidate in candidates:
            image=Path(candidate).resolve()
            if not image.is_file() or image.stat().st_size>67108864 or file_hash(image)!=sha:continue
            cp=subprocess.run([sys.executable,'-I','-S','-B','-c',PROBE,str(image)],capture_output=True,timeout=5,env=clean_env())
            if cp.returncode!=0 or len(cp.stdout)>4096:return base|{'reason':'NATIVE_PROBE_FAILED'}
            facts=json.loads(cp.stdout)
            if facts['version']!=version or file_hash(image)!=sha:return base|{'reason':'NATIVE_ID_CHANGED'}
            return base|facts|{'available':True,'path':str(image),'sha256':sha,
                'legacy_experiment_only':tuple(map(int,version.split('.')))<(1,0,21),'reason':'PINNED_CANDIDATE_OBSERVED'}
        return base|{'reason':'PIN_MISMATCH'}
    except (HarnessError,OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):return base|{'reason':'PROBE_FAILED'}
