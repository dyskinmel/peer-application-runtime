from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .errors import MigrationError
from .fs import absolute_no_symlink, available_bytes as probe_available_bytes
from .model import (
    CONVERTER_DIGEST,
    PLAN_PROFILE,
    SOURCE_STORE_VERSION,
    TARGET_SCHEMA_ID,
    TARGET_STORE_VERSION,
    MigrationPlan,
)
from .store import inspect_generation, read_active_pointer


def _separate_roots(store_root: Path, work_root: Path) -> tuple[Path, Path]:
    store_root = absolute_no_symlink(store_root, must_exist=True)
    work_root = absolute_no_symlink(work_root, must_exist=False)
    if work_root == store_root or work_root.is_relative_to(store_root) or store_root.is_relative_to(work_root):
        raise MigrationError("WORK_ROOT_NOT_SEPARATE")
    return store_root, work_root


def plan_migration(
    store_root: Path,
    work_root: Path,
    *,
    observed_at: str,
    capacity_reader: Callable[[Path], int] | None = None,
) -> MigrationPlan:
    if type(observed_at) is not str or not 1 <= len(observed_at) <= 128:
        raise MigrationError("OBSERVED_AT_INVALID")
    store_root, work_root = _separate_roots(store_root, work_root)
    pointer = read_active_pointer(store_root)
    if pointer.store_version != SOURCE_STORE_VERSION:
        raise MigrationError("UPGRADE_REQUIRED")
    source = inspect_generation(store_root, pointer.generation)
    if pointer.store_sha256 != source.store_sha256:
        raise MigrationError("ACTIVE_POINTER_MISMATCH")
    required = source.source_size * 3 + 4 * 1024 * 1024
    reader = probe_available_bytes if capacity_reader is None else capacity_reader
    try:
        available = reader(work_root)
    except MigrationError:
        raise
    except BaseException as exc:
        raise MigrationError("CAPACITY_UNAVAILABLE") from exc
    if type(available) is not int or type(available) is bool or available < 0:
        raise MigrationError("CAPACITY_UNAVAILABLE")
    if available < required:
        raise MigrationError("INSUFFICIENT_SPACE")
    provisional = MigrationPlan(
        store_root=store_root,
        work_root=work_root,
        observed_at=observed_at,
        source_generation=source.generation,
        source_store_sha256=source.store_sha256,
        source_digest=source.source_digest,
        source_size=source.source_size,
        versions=source.versions,
        inventory=source.inventory,
        seed_sha256=source.seed_sha256,
        frontier_sha256=source.frontier_sha256,
        converter_digest=CONVERTER_DIGEST,
        target_store_version=TARGET_STORE_VERSION,
        target_schema_id=TARGET_SCHEMA_ID,
        required_bytes=required,
        available_bytes=available,
        plan_digest="0" * 64,
        migration_id="migration-pending",
        target_generation="generation-pending",
    )
    digest = MigrationPlan.digest_identity(provisional.identity_dict())
    return MigrationPlan(
        **{
            **provisional.__dict__,
            "plan_digest": digest,
            "migration_id": "migration-" + digest[:20],
            "target_generation": "generation-" + digest[:24],
        }
    )
