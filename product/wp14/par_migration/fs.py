from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Callable

from .errors import MigrationError


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_text(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8") + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def read_strict_json(path: Path, *, max_bytes: int = 1024 * 1024):
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("not regular")
        size = path.stat().st_size
        if size < 2 or size > max_bytes:
            raise ValueError("size")
        return json.loads(path.read_text("utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise MigrationError("JSON_INVALID") from exc


def absolute_no_symlink(path: Path, *, must_exist: bool) -> Path:
    path = Path(os.path.abspath(path))
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        if probe.is_symlink():
            raise MigrationError("UNSAFE_PATH")
        resolved_probe = probe.resolve(strict=True)
        if resolved_probe != probe:
            raise MigrationError("UNSAFE_PATH")
        if must_exist:
            resolved = path.resolve(strict=True)
            if resolved != path:
                raise MigrationError("UNSAFE_PATH")
        return path
    except (OSError, RuntimeError) as exc:
        raise MigrationError("UNSAFE_PATH") from exc


def regular_file(path: Path) -> Path:
    path = absolute_no_symlink(path, must_exist=True)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise MigrationError("UNSAFE_PATH") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise MigrationError("UNSAFE_PATH")
    return path


def existing_capacity_root(path: Path) -> Path:
    path = absolute_no_symlink(path, must_exist=False)
    probe = path
    while not probe.exists():
        if probe == probe.parent:
            raise MigrationError("WORK_ROOT_INVALID")
        probe = probe.parent
    if not probe.is_dir():
        probe = probe.parent
    return absolute_no_symlink(probe, must_exist=True)


def available_bytes(path: Path) -> int:
    try:
        statvfs = os.statvfs(existing_capacity_root(path))
        return int(statvfs.f_bavail * statvfs.f_frsize)
    except OSError as exc:
        raise MigrationError("CAPACITY_UNAVAILABLE") from exc


def exact_keys(value: object, keys: set[str], code: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise MigrationError(code)
    return value


def sync_dir(path: Path) -> None:
    if os.name != "posix":
        raise MigrationError("POSIX_REQUIRED")
    path = absolute_no_symlink(path, must_exist=True)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise MigrationError("FSYNC_FAILED") from exc


def ensure_private_dir(path: Path) -> Path:
    path = absolute_no_symlink(path, must_exist=False)
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        raise MigrationError("WORK_ROOT_INVALID") from exc
    return absolute_no_symlink(path, must_exist=True)


def write_json_exclusive(path: Path, value: Any) -> None:
    path = absolute_no_symlink(path, must_exist=False)
    ensure_private_dir(path.parent)
    data = canonical_text(value).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(path.parent)
    except FileExistsError:
        raise MigrationError("DESTINATION_EXISTS") from None
    except OSError as exc:
        raise MigrationError("WRITE_FAILED") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    import secrets
    path = absolute_no_symlink(path, must_exist=False)
    ensure_private_dir(path.parent)
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    data = canonical_text(value).encode("utf-8")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    except OSError as exc:
        raise MigrationError("WRITE_FAILED") from exc
    finally:
        try:
            if temp.exists() and not temp.is_symlink():
                temp.unlink()
        except OSError:
            pass


def copy_file_fsync(source: Path, destination: Path) -> tuple[int, str]:
    import shutil
    source = regular_file(source)
    destination = absolute_no_symlink(destination, must_exist=False)
    ensure_private_dir(destination.parent)
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        dest_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(source_fd, "rb") as src, os.fdopen(dest_fd, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        sync_dir(destination.parent)
        return destination.stat().st_size, sha256_file(destination)
    except FileExistsError:
        raise MigrationError("DESTINATION_EXISTS") from None
    except OSError as exc:
        raise MigrationError("COPY_FAILED") from exc


def remove_owned_tree(path: Path) -> None:
    import shutil
    path = Path(os.path.abspath(path))
    if not path.exists():
        return
    if path.is_symlink():
        raise MigrationError("UNSAFE_PATH")
    for item in path.rglob("*"):
        if item.is_symlink():
            raise MigrationError("UNSAFE_PATH")
    try:
        shutil.rmtree(path)
        sync_dir(path.parent)
    except OSError as exc:
        raise MigrationError("CLEANUP_FAILED") from exc
