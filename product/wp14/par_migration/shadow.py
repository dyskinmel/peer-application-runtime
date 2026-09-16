from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from .backup import BackupManifest, migration_directory, require_verified_backup
from .errors import MigrationError
from .fs import (
    absolute_no_symlink,
    ensure_private_dir,
    read_strict_json,
    regular_file,
    remove_owned_tree,
    sha256_file,
    sync_dir,
    write_json_exclusive,
)
from .journal import MigrationJournal, STAGES
from .model import (
    SUPPORTED_CODECS,
    TARGET_SCHEMA_ID,
    TARGET_STORE_VERSION,
    MigrationPlan,
)

SHADOW_PROFILE = "par-local-migration-shadow-0057"

TARGET_DDL = """
CREATE TABLE store_metadata(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  generation TEXT NOT NULL,
  source_generation TEXT NOT NULL,
  wire_version TEXT NOT NULL,
  suite_version TEXT NOT NULL,
  schema_id TEXT NOT NULL,
  store_version INTEGER NOT NULL,
  sdk_version TEXT NOT NULL,
  ui_version TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  plan_digest TEXT NOT NULL,
  converter_digest TEXT NOT NULL,
  seed_sha256 TEXT NOT NULL,
  frontier_sha256 TEXT NOT NULL,
  backup_store_sha256 TEXT NOT NULL
);
CREATE TABLE operation_ledger(
  operation_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  outcome TEXT NOT NULL
);
CREATE TABLE outbox(
  operation_id TEXT PRIMARY KEY REFERENCES operation_ledger(operation_id),
  envelope BLOB NOT NULL,
  state TEXT NOT NULL
);
CREATE TABLE drafts(
  draft_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  payload BLOB NOT NULL,
  applied INTEGER NOT NULL CHECK(applied IN (0,1))
);
CREATE TABLE signed_objects(
  object_id TEXT PRIMARY KEY,
  codec TEXT NOT NULL,
  mandatory INTEGER NOT NULL CHECK(mandatory IN (0,1)),
  signed_bytes BLOB NOT NULL,
  applied INTEGER NOT NULL CHECK(applied IN (0,1)),
  ack_state TEXT NOT NULL,
  resigned INTEGER NOT NULL CHECK(resigned IN (0,1)),
  migration_status TEXT NOT NULL
);
CREATE TABLE migration_seed(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  seed_bytes BLOB NOT NULL,
  source_frontier BLOB NOT NULL,
  converter_digest TEXT NOT NULL,
  source_digest TEXT NOT NULL
);
""".strip()


@dataclass(frozen=True)
class ShadowManifest:
    plan_digest: str
    source_digest: str
    source_generation: str
    target_generation: str
    source_store_sha256: str
    backup_store_sha256: str
    store_sha256: str
    size: int
    versions: dict[str, Any]
    inventory: dict[str, int]
    seed_sha256: str
    frontier_sha256: str
    converter_digest: str
    unknown_mandatory_count: int
    logical_verified: bool
    schema_verified: bool
    hash_verified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": SHADOW_PROFILE,
            "planDigest": self.plan_digest,
            "sourceDigest": self.source_digest,
            "sourceGeneration": self.source_generation,
            "targetGeneration": self.target_generation,
            "sourceStoreSha256": self.source_store_sha256,
            "backupStoreSha256": self.backup_store_sha256,
            "storeSha256": self.store_sha256,
            "size": self.size,
            "versions": dict(self.versions),
            "inventory": dict(self.inventory),
            "seedSha256": self.seed_sha256,
            "frontierSha256": self.frontier_sha256,
            "converterDigest": self.converter_digest,
            "unknownMandatoryCount": self.unknown_mandatory_count,
            "logicalVerified": self.logical_verified,
            "schemaVerified": self.schema_verified,
            "hashVerified": self.hash_verified,
        }


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]


@lru_cache(maxsize=1)
def expected_target_schema() -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(TARGET_DDL)
        return _schema_objects(connection)
    finally:
        connection.close()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    path = regular_file(path)
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise MigrationError("SHADOW_INVALID")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise MigrationError("SHADOW_INVALID") from exc


def _source_connection(path: Path) -> sqlite3.Connection:
    path = regular_file(path)
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise MigrationError("BACKUP_INVALID") from exc


def _target_versions(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "wire": plan.versions["wire"],
        "suite": plan.versions["suite"],
        "schema": plan.target_schema_id,
        "store": plan.target_store_version,
        "sdk": plan.versions["sdk"],
        "ui": plan.versions["ui"],
    }


def _rows(connection: sqlite3.Connection, table: str, columns: str, order: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in connection.execute(f"SELECT {columns} FROM {table} ORDER BY {order}")]


def _expected_signed_rows(source: sqlite3.Connection) -> tuple[list[tuple[Any, ...]], int]:
    rows: list[tuple[Any, ...]] = []
    unknown_mandatory_count = 0
    for row in source.execute(
        "SELECT object_id,codec,mandatory,signed_bytes,applied,ack_state,resigned "
        "FROM signed_objects ORDER BY object_id"
    ):
        object_id, codec, mandatory, signed_bytes, applied, ack_state, resigned = tuple(row)
        if codec in SUPPORTED_CODECS:
            migration_status = "PRESERVED"
        elif mandatory == 1:
            applied = 0
            ack_state = "BLOCKED"
            resigned = 0
            migration_status = "UPGRADE_REQUIRED"
            unknown_mandatory_count += 1
        else:
            applied = 0
            ack_state = "OPAQUE"
            resigned = 0
            migration_status = "OPAQUE_OPTIONAL"
        rows.append(
            (
                object_id,
                codec,
                mandatory,
                signed_bytes,
                applied,
                ack_state,
                resigned,
                migration_status,
            )
        )
    return rows, unknown_mandatory_count


def _manifest_from_raw(raw: object) -> ShadowManifest:
    fields = {
        "profile",
        "planDigest",
        "sourceDigest",
        "sourceGeneration",
        "targetGeneration",
        "sourceStoreSha256",
        "backupStoreSha256",
        "storeSha256",
        "size",
        "versions",
        "inventory",
        "seedSha256",
        "frontierSha256",
        "converterDigest",
        "unknownMandatoryCount",
        "logicalVerified",
        "schemaVerified",
        "hashVerified",
    }
    if type(raw) is not dict or set(raw) != fields or raw["profile"] != SHADOW_PROFILE:
        raise MigrationError("SHADOW_INVALID")
    string_fields = (
        "planDigest",
        "sourceDigest",
        "sourceGeneration",
        "targetGeneration",
        "sourceStoreSha256",
        "backupStoreSha256",
        "storeSha256",
        "seedSha256",
        "frontierSha256",
        "converterDigest",
    )
    if any(type(raw[key]) is not str or not raw[key] for key in string_fields):
        raise MigrationError("SHADOW_INVALID")
    for key in (
        "planDigest",
        "sourceDigest",
        "sourceStoreSha256",
        "backupStoreSha256",
        "storeSha256",
        "seedSha256",
        "frontierSha256",
        "converterDigest",
    ):
        if len(raw[key]) != 64:
            raise MigrationError("SHADOW_INVALID")
    if type(raw["size"]) is not int or type(raw["size"]) is bool or raw["size"] < 1:
        raise MigrationError("SHADOW_INVALID")
    if (
        type(raw["unknownMandatoryCount"]) is not int
        or type(raw["unknownMandatoryCount"]) is bool
        or raw["unknownMandatoryCount"] < 0
    ):
        raise MigrationError("SHADOW_INVALID")
    if type(raw["versions"]) is not dict or type(raw["inventory"]) is not dict:
        raise MigrationError("SHADOW_INVALID")
    if any(raw[key] is not True for key in ("logicalVerified", "schemaVerified", "hashVerified")):
        raise MigrationError("SHADOW_INVALID")
    return ShadowManifest(
        plan_digest=raw["planDigest"],
        source_digest=raw["sourceDigest"],
        source_generation=raw["sourceGeneration"],
        target_generation=raw["targetGeneration"],
        source_store_sha256=raw["sourceStoreSha256"],
        backup_store_sha256=raw["backupStoreSha256"],
        store_sha256=raw["storeSha256"],
        size=raw["size"],
        versions=dict(raw["versions"]),
        inventory=dict(raw["inventory"]),
        seed_sha256=raw["seedSha256"],
        frontier_sha256=raw["frontierSha256"],
        converter_digest=raw["converterDigest"],
        unknown_mandatory_count=raw["unknownMandatoryCount"],
        logical_verified=True,
        schema_verified=True,
        hash_verified=True,
    )


def _validate_database(
    plan: MigrationPlan,
    backup: BackupManifest,
    target_path: Path,
) -> tuple[dict[str, int], int]:
    backup_path = migration_directory(plan) / "backup" / "store.sqlite"
    source = _source_connection(backup_path)
    target = _readonly_connection(target_path)
    try:
        if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("SHADOW_INVALID")
        if target.execute("PRAGMA user_version").fetchone()[0] != TARGET_STORE_VERSION:
            raise MigrationError("SHADOW_INVALID")
        if _schema_objects(target) != expected_target_schema():
            raise MigrationError("SHADOW_INVALID")

        metadata = target.execute(
            "SELECT generation,source_generation,wire_version,suite_version,schema_id,store_version,"
            "sdk_version,ui_version,source_digest,plan_digest,converter_digest,seed_sha256,"
            "frontier_sha256,backup_store_sha256 FROM store_metadata WHERE singleton=1"
        ).fetchall()
        expected_metadata = [
            (
                plan.target_generation,
                plan.source_generation,
                plan.versions["wire"],
                plan.versions["suite"],
                TARGET_SCHEMA_ID,
                TARGET_STORE_VERSION,
                plan.versions["sdk"],
                plan.versions["ui"],
                plan.source_digest,
                plan.plan_digest,
                plan.converter_digest,
                plan.seed_sha256,
                plan.frontier_sha256,
                backup.store_sha256,
            )
        ]
        if [tuple(row) for row in metadata] != expected_metadata:
            raise MigrationError("SHADOW_INVALID")

        for table, columns, order in (
            ("operation_ledger", "operation_id,state,payload_hash,outcome", "operation_id"),
            ("outbox", "operation_id,envelope,state", "operation_id"),
            ("drafts", "draft_id,document_id,payload,applied", "draft_id"),
        ):
            if _rows(source, table, columns, order) != _rows(target, table, columns, order):
                raise MigrationError("SHADOW_INVALID")

        expected_signed, unknown_mandatory_count = _expected_signed_rows(source)
        actual_signed = _rows(
            target,
            "signed_objects",
            "object_id,codec,mandatory,signed_bytes,applied,ack_state,resigned,migration_status",
            "object_id",
        )
        if actual_signed != expected_signed:
            raise MigrationError("SHADOW_INVALID")

        source_seed = source.execute(
            "SELECT seed_bytes,source_frontier FROM migration_seed WHERE singleton=1"
        ).fetchall()
        target_seed = target.execute(
            "SELECT seed_bytes,source_frontier,converter_digest,source_digest "
            "FROM migration_seed WHERE singleton=1"
        ).fetchall()
        if len(source_seed) != 1 or len(target_seed) != 1:
            raise MigrationError("SHADOW_INVALID")
        if tuple(target_seed[0]) != (
            source_seed[0]["seed_bytes"],
            source_seed[0]["source_frontier"],
            plan.converter_digest,
            plan.source_digest,
        ):
            raise MigrationError("SHADOW_INVALID")

        inventory = {
            "operationLedger": target.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0],
            "outbox": target.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            "drafts": target.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
            "signedObjects": target.execute("SELECT COUNT(*) FROM signed_objects").fetchone()[0],
        }
        if inventory != plan.inventory:
            raise MigrationError("SHADOW_INVALID")
        return inventory, unknown_mandatory_count
    except sqlite3.Error as exc:
        raise MigrationError("SHADOW_INVALID") from exc
    finally:
        source.close()
        target.close()


def _expected_manifest(
    plan: MigrationPlan,
    backup: BackupManifest,
    target_path: Path,
    inventory: dict[str, int],
    unknown_mandatory_count: int,
) -> ShadowManifest:
    return ShadowManifest(
        plan_digest=plan.plan_digest,
        source_digest=plan.source_digest,
        source_generation=plan.source_generation,
        target_generation=plan.target_generation,
        source_store_sha256=plan.source_store_sha256,
        backup_store_sha256=backup.store_sha256,
        store_sha256=sha256_file(target_path),
        size=target_path.stat().st_size,
        versions=_target_versions(plan),
        inventory=dict(inventory),
        seed_sha256=plan.seed_sha256,
        frontier_sha256=plan.frontier_sha256,
        converter_digest=plan.converter_digest,
        unknown_mandatory_count=unknown_mandatory_count,
        logical_verified=True,
        schema_verified=True,
        hash_verified=True,
    )


def _verify_shadow_directory(
    plan: MigrationPlan,
    backup: BackupManifest,
    directory: Path,
) -> ShadowManifest:
    try:
        directory = absolute_no_symlink(directory, must_exist=True)
        if not directory.is_dir():
            raise MigrationError("SHADOW_INVALID")
        entries = list(directory.iterdir())
        if {entry.name for entry in entries} != {"MANIFEST.json", "store.sqlite"}:
            raise MigrationError("SHADOW_INVALID")
        if any(entry.is_symlink() for entry in entries):
            raise MigrationError("SHADOW_INVALID")
        raw = read_strict_json(directory / "MANIFEST.json", max_bytes=1024 * 1024)
        manifest = _manifest_from_raw(raw)
        target_path = directory / "store.sqlite"
        inventory, unknown_mandatory_count = _validate_database(plan, backup, target_path)
        expected = _expected_manifest(plan, backup, target_path, inventory, unknown_mandatory_count)
        if manifest != expected:
            raise MigrationError("SHADOW_INVALID")
        return manifest
    except MigrationError as exc:
        if exc.code == "SHADOW_INVALID":
            raise
        raise MigrationError("SHADOW_INVALID") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MigrationError("SHADOW_INVALID") from exc


def verify_shadow(plan: MigrationPlan, location: Path | None = None) -> ShadowManifest:
    try:
        backup = require_verified_backup(plan)
        directory = migration_directory(plan) / "shadow" if location is None else Path(location)
        return _verify_shadow_directory(plan, backup, directory)
    except MigrationError as exc:
        if exc.code == "SHADOW_INVALID":
            raise
        raise MigrationError("SHADOW_INVALID") from exc


def _advance_to(plan: MigrationPlan, target: str) -> MigrationJournal:
    if target not in STAGES:
        raise MigrationError("JOURNAL_STAGE_INVALID")
    current = MigrationJournal.load(plan)
    while STAGES.index(current.stage) < STAGES.index(target):
        next_stage = STAGES[STAGES.index(current.stage) + 1]
        current = MigrationJournal.advance(plan, next_stage)
    return current


def _insert_rows(
    target: sqlite3.Connection,
    statement: str,
    rows: Iterable[tuple[Any, ...]],
) -> None:
    target.executemany(statement, rows)


def _build_database(
    plan: MigrationPlan,
    backup: BackupManifest,
    target_path: Path,
    observer: Callable[[str], None],
) -> None:
    backup_path = migration_directory(plan) / "backup" / "store.sqlite"
    source = _source_connection(backup_path)
    target = sqlite3.connect(target_path, isolation_level=None)
    try:
        target.execute("PRAGMA journal_mode=DELETE")
        target.execute("PRAGMA synchronous=FULL")
        target.execute("PRAGMA foreign_keys=ON")
        target.executescript("BEGIN IMMEDIATE;\n" + TARGET_DDL)
        observer("shadow.after_schema")

        target.execute(
            "INSERT INTO store_metadata VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                plan.target_generation,
                plan.source_generation,
                plan.versions["wire"],
                plan.versions["suite"],
                TARGET_SCHEMA_ID,
                TARGET_STORE_VERSION,
                plan.versions["sdk"],
                plan.versions["ui"],
                plan.source_digest,
                plan.plan_digest,
                plan.converter_digest,
                plan.seed_sha256,
                plan.frontier_sha256,
                backup.store_sha256,
            ),
        )
        _insert_rows(
            target,
            "INSERT INTO operation_ledger VALUES(?,?,?,?)",
            _rows(source, "operation_ledger", "operation_id,state,payload_hash,outcome", "operation_id"),
        )
        _insert_rows(
            target,
            "INSERT INTO outbox VALUES(?,?,?)",
            _rows(source, "outbox", "operation_id,envelope,state", "operation_id"),
        )
        _insert_rows(
            target,
            "INSERT INTO drafts VALUES(?,?,?,?)",
            _rows(source, "drafts", "draft_id,document_id,payload,applied", "draft_id"),
        )
        signed_rows, _ = _expected_signed_rows(source)
        _insert_rows(target, "INSERT INTO signed_objects VALUES(?,?,?,?,?,?,?,?)", signed_rows)
        seed = source.execute(
            "SELECT seed_bytes,source_frontier FROM migration_seed WHERE singleton=1"
        ).fetchone()
        if seed is None:
            raise MigrationError("BACKUP_INVALID")
        target.execute(
            "INSERT INTO migration_seed VALUES(1,?,?,?,?)",
            (seed["seed_bytes"], seed["source_frontier"], plan.converter_digest, plan.source_digest),
        )
        target.execute(f"PRAGMA user_version={TARGET_STORE_VERSION}")
        observer("shadow.after_rows")
        target.execute("COMMIT")
    except BaseException:
        if target.in_transaction:
            target.execute("ROLLBACK")
        raise
    finally:
        target.close()
        source.close()

    try:
        os.chmod(target_path, 0o600)
        fd = os.open(target_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        sync_dir(target_path.parent)
    except OSError as exc:
        raise MigrationError("FSYNC_FAILED") from exc
    observer("shadow.after_fsync")


def build_shadow(
    plan: MigrationPlan,
    observer: Callable[[str], None] | None = None,
) -> ShadowManifest:
    observer = (lambda stage: None) if observer is None else observer
    backup = require_verified_backup(plan)
    directory = migration_directory(plan, create=True)
    MigrationJournal.initialize(plan)
    _advance_to(plan, "BACKUP_VERIFIED")

    shadow = directory / "shadow"
    pending = directory / "shadow.pending"
    if shadow.exists():
        if pending.exists():
            remove_owned_tree(pending)
        manifest = _verify_shadow_directory(plan, backup, shadow)
        _advance_to(plan, "SHADOW_VERIFIED")
        return manifest

    if pending.exists():
        remove_owned_tree(pending)
    ensure_private_dir(pending)
    target_path = pending / "store.sqlite"
    _build_database(plan, backup, target_path, observer)
    inventory, unknown_mandatory_count = _validate_database(plan, backup, target_path)
    manifest = _expected_manifest(plan, backup, target_path, inventory, unknown_mandatory_count)
    write_json_exclusive(pending / "MANIFEST.json", manifest.to_dict())
    _verify_shadow_directory(plan, backup, pending)
    os.rename(pending, shadow)
    sync_dir(directory)
    _advance_to(plan, "SHADOW_BUILT")
    manifest = _verify_shadow_directory(plan, backup, shadow)
    observer("verify.after_shadow")
    _advance_to(plan, "SHADOW_VERIFIED")
    return manifest
