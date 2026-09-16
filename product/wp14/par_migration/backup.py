from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import MigrationError
from .fs import (
    absolute_no_symlink,
    copy_file_fsync,
    ensure_private_dir,
    read_strict_json,
    remove_owned_tree,
    sha256_file,
    sync_dir,
    write_json_exclusive,
)
from .journal import MigrationJournal
from .model import MigrationPlan
from .store import inspect_database, inspect_generation, read_active_pointer

BACKUP_PROFILE = "par-local-migration-backup-0057"


@dataclass(frozen=True)
class BackupManifest:
    plan_digest: str
    source_digest: str
    source_generation: str
    store_sha256: str
    size: int
    versions: dict[str, Any]
    inventory: dict[str, int]
    seed_sha256: str
    frontier_sha256: str
    readback_verified: bool

    def to_dict(self):
        return {
            "profile": BACKUP_PROFILE,
            "planDigest": self.plan_digest,
            "sourceDigest": self.source_digest,
            "sourceGeneration": self.source_generation,
            "storeSha256": self.store_sha256,
            "size": self.size,
            "versions": dict(self.versions),
            "inventory": dict(self.inventory),
            "seedSha256": self.seed_sha256,
            "frontierSha256": self.frontier_sha256,
            "readbackVerified": self.readback_verified,
        }


def migration_directory(plan: MigrationPlan, *, create: bool = False) -> Path:
    path = Path(os.path.abspath(plan.work_root / plan.migration_id))
    if create:
        ensure_private_dir(plan.work_root)
        ensure_private_dir(path)
    return path


def _verify_current_source(plan: MigrationPlan):
    pointer = read_active_pointer(plan.store_root)
    if pointer.generation != plan.source_generation:
        raise MigrationError("SOURCE_DIGEST_MISMATCH")
    observation = inspect_generation(plan.store_root, pointer.generation)
    if pointer.store_sha256 != observation.store_sha256:
        raise MigrationError("SOURCE_DIGEST_MISMATCH")
    if (
        observation.source_digest != plan.source_digest
        or observation.store_sha256 != plan.source_store_sha256
        or observation.inventory != plan.inventory
        or observation.versions != plan.versions
        or observation.seed_sha256 != plan.seed_sha256
        or observation.frontier_sha256 != plan.frontier_sha256
    ):
        raise MigrationError("SOURCE_DIGEST_MISMATCH")
    return observation


def _manifest_from_raw(raw: object) -> BackupManifest:
    fields = {
        "profile", "planDigest", "sourceDigest", "sourceGeneration", "storeSha256", "size",
        "versions", "inventory", "seedSha256", "frontierSha256", "readbackVerified",
    }
    if type(raw) is not dict or set(raw) != fields or raw["profile"] != BACKUP_PROFILE:
        raise MigrationError("BACKUP_INVALID")
    if type(raw["size"]) is not int or type(raw["size"]) is bool or raw["size"] < 1:
        raise MigrationError("BACKUP_INVALID")
    if raw["readbackVerified"] is not True or type(raw["versions"]) is not dict or type(raw["inventory"]) is not dict:
        raise MigrationError("BACKUP_INVALID")
    for key in ("planDigest", "sourceDigest", "storeSha256", "seedSha256", "frontierSha256"):
        if type(raw[key]) is not str or len(raw[key]) != 64:
            raise MigrationError("BACKUP_INVALID")
    if type(raw["sourceGeneration"]) is not str:
        raise MigrationError("BACKUP_INVALID")
    return BackupManifest(
        raw["planDigest"], raw["sourceDigest"], raw["sourceGeneration"], raw["storeSha256"],
        raw["size"], dict(raw["versions"]), dict(raw["inventory"]), raw["seedSha256"],
        raw["frontierSha256"], True,
    )


def _verify_backup_directory(plan: MigrationPlan, directory: Path) -> BackupManifest:
    try:
        directory = absolute_no_symlink(directory, must_exist=True)
        if not directory.is_dir():
            raise MigrationError("BACKUP_INVALID")
        entries = {entry.name for entry in directory.iterdir()}
        if entries != {"MANIFEST.json", "store.sqlite"} or any(entry.is_symlink() for entry in directory.iterdir()):
            raise MigrationError("BACKUP_INVALID")
        raw = read_strict_json(directory / "MANIFEST.json", max_bytes=1024 * 1024)
        manifest = _manifest_from_raw(raw)
        db = directory / "store.sqlite"
        if manifest.plan_digest != plan.plan_digest or manifest.source_digest != plan.source_digest or manifest.source_generation != plan.source_generation:
            raise MigrationError("BACKUP_INVALID")
        if db.stat().st_size != manifest.size or sha256_file(db) != manifest.store_sha256:
            raise MigrationError("BACKUP_INVALID")
        observation = inspect_database(db, plan.source_generation)
        if (
            observation.store_sha256 != manifest.store_sha256
            or observation.source_digest != manifest.source_digest
            or observation.versions != manifest.versions
            or observation.inventory != manifest.inventory
            or observation.seed_sha256 != manifest.seed_sha256
            or observation.frontier_sha256 != manifest.frontier_sha256
        ):
            raise MigrationError("BACKUP_INVALID")
        if (
            manifest.store_sha256 != plan.source_store_sha256
            or manifest.versions != plan.versions
            or manifest.inventory != plan.inventory
            or manifest.seed_sha256 != plan.seed_sha256
            or manifest.frontier_sha256 != plan.frontier_sha256
        ):
            raise MigrationError("BACKUP_INVALID")
        return manifest
    except MigrationError as exc:
        if exc.code == "BACKUP_INVALID":
            raise
        raise MigrationError("BACKUP_INVALID") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MigrationError("BACKUP_INVALID") from exc


def verify_backup(plan: MigrationPlan) -> BackupManifest:
    return _verify_backup_directory(plan, migration_directory(plan) / "backup")


def require_verified_backup(plan: MigrationPlan) -> BackupManifest:
    backup = migration_directory(plan) / "backup"
    if not backup.is_dir():
        raise MigrationError("BACKUP_REQUIRED")
    return verify_backup(plan)


def create_verified_backup(plan: MigrationPlan, observer: Callable[[str], None] | None = None) -> BackupManifest:
    observer = (lambda stage: None) if observer is None else observer
    source = _verify_current_source(plan)
    directory = migration_directory(plan, create=True)
    journal = MigrationJournal.initialize(plan)
    backup = directory / "backup"
    if backup.exists():
        manifest = verify_backup(plan)
        MigrationJournal.advance(plan, "BACKUP_VERIFIED")
        return manifest
    pending = directory / "backup.pending"
    if pending.exists():
        remove_owned_tree(pending)
    ensure_private_dir(pending)
    try:
        observer("backup.before_copy")
        size, digest = copy_file_fsync(source.db_path, pending / "store.sqlite")
        observer("backup.after_copy")
        readback = inspect_database(pending / "store.sqlite", plan.source_generation)
        manifest = BackupManifest(
            plan.plan_digest,
            plan.source_digest,
            plan.source_generation,
            digest,
            size,
            readback.versions,
            readback.inventory,
            readback.seed_sha256,
            readback.frontier_sha256,
            True,
        )
        if (
            readback.source_digest != plan.source_digest
            or digest != plan.source_store_sha256
            or size != plan.source_size
        ):
            raise MigrationError("BACKUP_INVALID")
        write_json_exclusive(pending / "MANIFEST.json", manifest.to_dict())
        _verify_backup_directory(plan, pending)
        observer("backup.after_readback")
        os.rename(pending, backup)
        sync_dir(directory)
        manifest = verify_backup(plan)
        MigrationJournal.advance(plan, "BACKUP_VERIFIED")
        return manifest
    except BaseException:
        # Preserve incomplete data only while the process is alive. A later resume
        # removes this owned, non-active staging directory after path validation.
        raise
