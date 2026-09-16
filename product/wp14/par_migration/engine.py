from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .backup import create_verified_backup, migration_directory
from .errors import MigrationError
from .fs import (
    absolute_no_symlink,
    read_strict_json,
    regular_file,
    sha256_file,
    sync_dir,
    write_json_exclusive,
)
from .journal import MigrationJournal, STAGES
from .model import (
    SOURCE_SCHEMA_ID,
    SOURCE_STORE_VERSION,
    TARGET_SCHEMA_ID,
    TARGET_STORE_VERSION,
    ActivePointer,
    MigrationPlan,
)
from .shadow import (
    ShadowManifest,
    _manifest_from_raw,
    _schema_objects,
    build_shadow,
    expected_target_schema,
    verify_shadow,
)
from .store import expected_source_schema, inspect_generation, read_active_pointer


class _MigrationLease:
    def __init__(self, store_root: Path):
        self.store_root = absolute_no_symlink(store_root, must_exist=True)
        self.fd: int | None = None

    def __enter__(self):
        if os.name != "posix":
            raise MigrationError("POSIX_REQUIRED")
        import fcntl

        path = self.store_root / ".migration.lock"
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
            ):
                raise MigrationError("UNSAFE_PATH")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MigrationError("MIGRATION_BUSY") from None
            self.fd = fd
            return self
        except BaseException:
            if 'fd' in locals():
                os.close(fd)
            raise

    def __exit__(self, exc_type, exc, traceback):
        if self.fd is not None:
            import fcntl

            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        return False


@dataclass(frozen=True)
class MigrationResult:
    plan_digest: str
    source_generation: str
    target_generation: str
    active_generation: str
    target_store_sha256: str
    activated: bool
    old_generation_retained: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "planDigest": self.plan_digest,
            "sourceGeneration": self.source_generation,
            "targetGeneration": self.target_generation,
            "activeGeneration": self.active_generation,
            "targetStoreSha256": self.target_store_sha256,
            "activated": self.activated,
            "oldGenerationRetained": self.old_generation_retained,
        }


def _advance_to(plan: MigrationPlan, target: str) -> MigrationJournal:
    if target not in STAGES:
        raise MigrationError("JOURNAL_STAGE_INVALID")
    current = MigrationJournal.load(plan)
    while STAGES.index(current.stage) < STAGES.index(target):
        current = MigrationJournal.advance(plan, STAGES[STAGES.index(current.stage) + 1])
    return current


def _device_id(path: Path) -> int:
    try:
        return int(os.stat(path, follow_symlinks=False).st_dev)
    except OSError as exc:
        raise MigrationError("DEVICE_PROBE_FAILED") from exc


def _target_root(plan: MigrationPlan) -> Path:
    return plan.store_root / "generations" / plan.target_generation


def _source_root(plan: MigrationPlan) -> Path:
    return plan.store_root / "generations" / plan.source_generation


def _require_source_active(plan: MigrationPlan) -> ActivePointer:
    pointer = read_active_pointer(plan.store_root)
    if pointer.generation != plan.source_generation:
        if pointer.generation == plan.target_generation:
            return pointer
        raise MigrationError("ACTIVE_GENERATION_CHANGED")
    if pointer.store_version != SOURCE_STORE_VERSION or pointer.store_sha256 != plan.source_store_sha256:
        raise MigrationError("SOURCE_DIGEST_MISMATCH")
    observation = inspect_generation(plan.store_root, plan.source_generation)
    if (
        observation.store_sha256 != plan.source_store_sha256
        or observation.source_digest != plan.source_digest
        or observation.versions != plan.versions
        or observation.inventory != plan.inventory
        or observation.seed_sha256 != plan.seed_sha256
        or observation.frontier_sha256 != plan.frontier_sha256
    ):
        raise MigrationError("SOURCE_DIGEST_MISMATCH")
    return pointer


def _verify_published(plan: MigrationPlan) -> ShadowManifest:
    target = _target_root(plan)
    try:
        return verify_shadow(plan, target)
    except MigrationError as exc:
        raise MigrationError("PUBLISHED_INVALID") from exc


def _require_target_pointer(plan: MigrationPlan, manifest: ShadowManifest) -> ActivePointer:
    pointer = read_active_pointer(plan.store_root)
    if (
        pointer.generation != plan.target_generation
        or pointer.store_version != TARGET_STORE_VERSION
        or pointer.store_sha256 != manifest.store_sha256
    ):
        raise MigrationError("ACTIVE_POINTER_MISMATCH")
    return pointer


def _result(plan: MigrationPlan, manifest: ShadowManifest) -> MigrationResult:
    return MigrationResult(
        plan_digest=plan.plan_digest,
        source_generation=plan.source_generation,
        target_generation=plan.target_generation,
        active_generation=plan.target_generation,
        target_store_sha256=manifest.store_sha256,
        activated=True,
        old_generation_retained=_source_root(plan).is_dir(),
    )


def _remove_owned_pointer_temp(plan: MigrationPlan, temp: Path) -> None:
    if not temp.exists() and not temp.is_symlink():
        return
    try:
        temp = absolute_no_symlink(temp, must_exist=True)
        if not temp.is_file():
            raise MigrationError("UNSAFE_PATH")
        temp.unlink()
        sync_dir(plan.store_root)
    except MigrationError:
        raise
    except OSError as exc:
        raise MigrationError("WRITE_FAILED") from exc


def _switch_pointer(
    plan: MigrationPlan,
    manifest: ShadowManifest,
    observer: Callable[[str], None],
) -> None:
    temp = plan.store_root / f".ACTIVE.{plan.migration_id}.pending"
    _remove_owned_pointer_temp(plan, temp)
    pointer = ActivePointer(plan.target_generation, manifest.store_sha256, TARGET_STORE_VERSION)
    write_json_exclusive(temp, pointer.to_dict())
    observer("switch.before_replace")
    try:
        os.replace(temp, plan.store_root / "ACTIVE.json")
        sync_dir(plan.store_root)
    except OSError as exc:
        raise MigrationError("POINTER_SWITCH_FAILED") from exc
    observer("switch.after_replace")


def _run_migration_locked(
    plan: MigrationPlan,
    observer: Callable[[str], None],
) -> MigrationResult:
    active = read_active_pointer(plan.store_root)
    if active.generation == plan.target_generation:
        manifest = _verify_published(plan)
        _require_target_pointer(plan, manifest)
        _advance_to(plan, "ACTIVATED")
        return _result(plan, manifest)
    if active.generation != plan.source_generation:
        raise MigrationError("ACTIVE_GENERATION_CHANGED")
    _require_source_active(plan)

    create_verified_backup(plan, observer=observer)
    target = _target_root(plan)
    shadow = migration_directory(plan) / "shadow"

    if target.exists() or target.is_symlink():
        manifest = _verify_published(plan)
        _advance_to(plan, "PUBLISHED")
    else:
        manifest = build_shadow(plan, observer=observer)
        _require_source_active(plan)
        generations = absolute_no_symlink(plan.store_root / "generations", must_exist=True)
        if _device_id(shadow) != _device_id(generations):
            raise MigrationError("CROSS_DEVICE_PUBLISH")
        observer("publish.before_rename")
        try:
            os.rename(shadow, target)
            sync_dir(generations)
        except OSError as exc:
            raise MigrationError("PUBLISH_FAILED") from exc
        observer("publish.after_rename")
        manifest = _verify_published(plan)
        _advance_to(plan, "PUBLISHED")

    active = _require_source_active(plan)
    if active.generation == plan.target_generation:
        _require_target_pointer(plan, manifest)
        _advance_to(plan, "ACTIVATED")
        return _result(plan, manifest)

    _switch_pointer(plan, manifest, observer)
    manifest = _verify_published(plan)
    _require_target_pointer(plan, manifest)
    _advance_to(plan, "ACTIVATED")
    return _result(plan, manifest)


def run_migration(
    plan: MigrationPlan,
    observer: Callable[[str], None] | None = None,
) -> MigrationResult:
    callback = (lambda stage: None) if observer is None else observer
    with _MigrationLease(plan.store_root):
        return _run_migration_locked(plan, callback)


def resume_migration(
    plan: MigrationPlan,
    observer: Callable[[str], None] | None = None,
) -> MigrationResult:
    return run_migration(plan, observer=observer)


def _validate_supported_versions(value: Iterable[int]) -> frozenset[int]:
    try:
        versions = frozenset(value)
    except TypeError as exc:
        raise MigrationError("SUPPORTED_VERSIONS_INVALID") from exc
    if not versions or any(type(item) is not int or type(item) is bool or item < 0 for item in versions):
        raise MigrationError("SUPPORTED_VERSIONS_INVALID")
    return versions


def _open_immutable(path: Path) -> sqlite3.Connection:
    path = regular_file(path)
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise MigrationError("ACTIVE_STORE_NOT_QUIESCENT")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise MigrationError("ACTIVE_STORE_OPEN_FAILED") from exc


def open_active_readonly(
    store_root: Path,
    supported_versions: Iterable[int] = frozenset({SOURCE_STORE_VERSION, TARGET_STORE_VERSION}),
) -> sqlite3.Connection:
    supported = _validate_supported_versions(supported_versions)
    pointer = read_active_pointer(store_root)
    known = frozenset({SOURCE_STORE_VERSION, TARGET_STORE_VERSION})
    if pointer.store_version not in known:
        raise MigrationError("UPGRADE_REQUIRED")
    if pointer.store_version not in supported:
        raise MigrationError("DOWNGRADE_REFUSED")

    generation_root = absolute_no_symlink(
        Path(store_root) / "generations" / pointer.generation,
        must_exist=True,
    )
    if not generation_root.is_dir():
        raise MigrationError("GENERATION_MISSING")
    db_path = regular_file(generation_root / "store.sqlite")
    if sha256_file(db_path) != pointer.store_sha256:
        raise MigrationError("ACTIVE_POINTER_MISMATCH")

    connection = _open_immutable(db_path)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("ACTIVE_STORE_CORRUPT")
        if connection.execute("PRAGMA user_version").fetchone()[0] != pointer.store_version:
            raise MigrationError("ACTIVE_POINTER_MISMATCH")

        if pointer.store_version == SOURCE_STORE_VERSION:
            if _schema_objects(connection) != expected_source_schema():
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
            metadata = connection.execute(
                "SELECT generation,schema_id,store_version FROM store_metadata WHERE singleton=1"
            ).fetchall()
            if [tuple(row) for row in metadata] != [
                (pointer.generation, SOURCE_SCHEMA_ID, SOURCE_STORE_VERSION)
            ]:
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
        else:
            entries = {entry.name for entry in generation_root.iterdir()}
            if entries != {"MANIFEST.json", "store.sqlite"}:
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
            if _schema_objects(connection) != expected_target_schema():
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
            metadata = connection.execute(
                "SELECT generation,schema_id,store_version FROM store_metadata WHERE singleton=1"
            ).fetchall()
            if [tuple(row) for row in metadata] != [
                (pointer.generation, TARGET_SCHEMA_ID, TARGET_STORE_VERSION)
            ]:
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
            raw_manifest = read_strict_json(generation_root / "MANIFEST.json", max_bytes=1024 * 1024)
            manifest = _manifest_from_raw(raw_manifest)
            if (
                manifest.target_generation != pointer.generation
                or manifest.store_sha256 != pointer.store_sha256
                or manifest.versions.get("schema") != TARGET_SCHEMA_ID
                or manifest.versions.get("store") != TARGET_STORE_VERSION
            ):
                raise MigrationError("ACTIVE_SCHEMA_INVALID")
        return connection
    except BaseException:
        connection.close()
        raise
