"""Strict data and filesystem boundary helpers. No external dependencies."""
from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

class HarnessError(Exception):
    def __init__(self, code: str, detail: str = '') -> None:
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')

def valid_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', value):
        raise HarnessError('INVALID_ID', str(value))
    return value

def _pairs(pairs: list) -> dict:
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError('duplicate key: '+k)
        out[k] = v
    return out

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (ValueError, OSError, UnicodeError) as exc:
        raise HarnessError('INVALID_JSON', f'{path.name}: {exc}') from exc

def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def safe_path(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or '\\' in rel or '\0' in rel:
        raise HarnessError('UNSAFE_PATH', str(rel))
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or ':' in rel or rel.startswith('/'):
        raise HarnessError('UNSAFE_PATH', rel)
    root = root.resolve()
    current = root
    for part in p.parts:
        current = current/part
        if current.is_symlink():
            raise HarnessError('UNSAFE_PATH', 'symlink: '+rel)
    if not current.resolve().is_relative_to(root):
        raise HarnessError('UNSAFE_PATH', rel)
    return current

def atomic_json(path: Path, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        if os.name == 'posix':
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    finally:
        if os.path.exists(name): os.unlink(name)

def clean_env() -> dict[str, str]:
    allowed = ('PATH','SystemRoot','WINDIR','TEMP','TMP','LANG','LC_ALL')
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONUTF8='1')
    return env
