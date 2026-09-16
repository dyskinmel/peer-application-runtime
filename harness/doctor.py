"""Bounded local capability probe. Never enumerate environment values or use network."""
from __future__ import annotations
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from .common import clean_env, digest, file_hash

def probe(tool_names: list[str]|None=None, *, root: Path|None=None) -> dict:
    supported=('git','rustc','cargo','node','tsc','cc','cmake')
    names=set((*supported,'sodium','unix_peercred') if tool_names is None else tool_names)
    scope=sorted(names|{'python'})
    tools={}; caps={'python':sys.version_info >= (3,10),'sqlite':True,'posix':os.name=='posix'}
    for unknown in names-set(supported)-{'python','sqlite','posix','sodium','unix_peercred'}:caps[unknown]=False
    tools['python']={'path':str(Path(sys.executable).resolve()),'version':platform.python_version(),'sha256':file_hash(Path(sys.executable).resolve())}
    for name in supported:
        if name not in names:continue
        path=shutil.which(name); item={'available':False,'path':path,'version':None}
        if path:
            try:
                cp=subprocess.run([path,'--version'],capture_output=True,timeout=3,env=clean_env())
                text=(cp.stdout+cp.stderr).decode('utf-8',errors='replace')[:1000]
                item.update(available=cp.returncode==0,version=text.splitlines()[0] if text else '',sha256=file_hash(Path(path).resolve()))
            except (OSError,subprocess.TimeoutExpired) as exc:
                item['reason']=type(exc).__name__
        caps[name]=item['available'];tools[name]=item
    facts={'scope':scope,'system':platform.system(),'machine':platform.machine(),'python_implementation':platform.python_implementation(),'sqlite':sqlite3.sqlite_version,'tools':tools,'capabilities':caps,'network_enforcement':'NOT_PROVIDED','real_devices':'NOT_PROBED','native_process_group_cleanup':sys.platform!='win32'}
    if 'sqlite' in names:
        # Bind the loaded extension and the runtime source/options. A matching
        # version string alone cannot distinguish a patched SQLite build.
        import _sqlite3
        conn=sqlite3.connect(':memory:')
        try:
            extension=Path(_sqlite3.__file__).resolve()
            runtime={'version':sqlite3.sqlite_version,'source_id':conn.execute('SELECT sqlite_source_id()').fetchone()[0],
                     'compile_options':sorted(row[0] for row in conn.execute('PRAGMA compile_options')),
                     'extension_path':str(extension),'extension_sha256':file_hash(extension),
                     'production_qualified':False,'dynamic_library_coverage':'EXTENSION_ONLY'}
            # Linux can identify the loaded libsqlite3 image without launching a
            # loader or accepting a PATH-based substitute. Other hosts stay explicit.
            maps=Path('/proc/self/maps')
            if maps.is_file():
                images=set()
                for line in maps.read_text().splitlines():
                    parts=line.split(maxsplit=5)
                    if len(parts)==6 and parts[5].startswith('/') and 'libsqlite3' in Path(parts[5]).name:
                        image=Path(parts[5])
                        if image.is_file():images.add(image.resolve())
                runtime['loaded_libraries']=[{'path':str(p),'sha256':file_hash(p)} for p in sorted(images)]
                if images:runtime['dynamic_library_coverage']='OBSERVED_LIBSQLITE3_IMAGES'
            facts['sqlite_runtime']=runtime
        finally:conn.close()
    if 'sodium' in names:
        from .native_crypto import measure
        facts['crypto_runtime']=measure(Path(__file__).resolve().parents[1] if root is None else root)
        facts['capabilities']['sodium']=facts['crypto_runtime']['available']
    if 'unix_peercred' in names:
        # No public bind, PID-dependent fingerprint or permission fallback.
        import socket,struct,_socket
        runtime={'available':False,'transport':'AF_UNIX_SOCKETPAIR','same_uid_verified':False,'public_listener':False}
        caps['unix_peercred']=False
        try:
            if not sys.platform.startswith('linux') or not hasattr(socket,'SO_PEERCRED'):raise OSError('unsupported')
            native_file=getattr(_socket,'__file__',None)
            image=Path(native_file or sys.executable).resolve()
            runtime.update(image_kind='EXTENSION' if native_file else 'BUILTIN_IN_EXECUTABLE',image_path=str(image),image_sha256=file_hash(image))
            a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
            try:
                _,uid,_=struct.unpack('3i',a.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
                if uid!=os.getuid():raise OSError('credential mismatch')
                b.sendall(b'x');a.settimeout(.2)
                if a.recv(1)!=b'x':raise OSError('socket probe')
            finally:a.close();b.close()
            runtime.update(available=True,same_uid_verified=True);caps['unix_peercred']=True
        except (OSError,AttributeError,ValueError) as exc:runtime['reason']=type(exc).__name__
        facts['unix_socket_runtime']=runtime
    facts['fingerprint']=digest(facts)
    return facts
