from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .errors import MigrationError
from .fs import (
    absolute_no_symlink,
    canonical_bytes,
    canonical_text,
    exact_keys,
    read_strict_json,
    regular_file,
    sha256_bytes,
    sha256_file,
)
from .model import (
    ActivePointer,
    DEFAULT_VERSIONS,
    ROOT_PROFILE,
    SOURCE_SCHEMA_ID,
    SOURCE_STORE_VERSION,
    SourceObservation,
    valid_generation,
    valid_sha,
    validate_versions,
)

SOURCE_DDL = """
CREATE TABLE store_metadata(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  generation TEXT NOT NULL,
  wire_version TEXT NOT NULL,
  suite_version TEXT NOT NULL,
  schema_id TEXT NOT NULL,
  store_version INTEGER NOT NULL,
  sdk_version TEXT NOT NULL,
  ui_version TEXT NOT NULL
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
  resigned INTEGER NOT NULL CHECK(resigned IN (0,1))
);
CREATE TABLE migration_seed(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  seed_bytes BLOB NOT NULL,
  source_frontier BLOB NOT NULL
);
""".strip()


def _schema_objects(connection: sqlite3.Connection):
    return [tuple(row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    )]


@lru_cache(maxsize=1)
def expected_source_schema():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SOURCE_DDL)
        return _schema_objects(connection)
    finally:
        connection.close()


def _strict_text(value: object, code: str, *, max_length: int = 256) -> str:
    if type(value) is not str or not 1 <= len(value) <= max_length:
        raise MigrationError(code)
    return value


def _strict_blob(value: object, code: str, *, max_length: int = 1024 * 1024) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= max_length:
        raise MigrationError(code)
    return value


def _strict_bool_int(value: object, code: str) -> int:
    if type(value) is not int or type(value) is bool or value not in (0, 1):
        raise MigrationError(code)
    return value


def _write_pointer(store_root: Path, pointer: ActivePointer) -> None:
    path = store_root / "ACTIVE.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_text(pointer.to_dict()))
        stream.flush()
        os.fsync(stream.fileno())


def create_v1_store(
    root: Path,
    *,
    generation: str,
    versions: dict[str, Any] | None = None,
    ledger: Iterable[dict[str, Any]],
    outbox: Iterable[dict[str, Any]],
    drafts: Iterable[dict[str, Any]],
    signed_objects: Iterable[dict[str, Any]],
    seed_bytes: bytes,
    source_frontier: bytes,
) -> None:
    """Create a closed deterministic local fixture used by tests and demos.

    This helper is not a migration path and never opens a network endpoint.
    """
    root = Path(os.path.abspath(root))
    if root.exists():
        raise MigrationError("STORE_EXISTS")
    generation = valid_generation(generation)
    versions = validate_versions(dict(DEFAULT_VERSIONS if versions is None else versions))
    generation_root = root / "generations" / generation
    generation_root.mkdir(parents=True, mode=0o700)
    db_path = generation_root / "store.sqlite"
    connection = sqlite3.connect(db_path, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("BEGIN IMMEDIATE;\n" + SOURCE_DDL)
        connection.execute(
            "INSERT INTO store_metadata VALUES(1,?,?,?,?,?,?,?)",
            (
                generation,
                versions["wire"],
                versions["suite"],
                versions["schema"],
                versions["store"],
                versions["sdk"],
                versions["ui"],
            ),
        )
        for row in ledger:
            exact_keys(row, {"operation_id", "state", "payload_hash", "outcome"}, "LEDGER_FIELDS")
            connection.execute(
                "INSERT INTO operation_ledger VALUES(?,?,?,?)",
                (
                    _strict_text(row["operation_id"], "OPERATION_ID"),
                    _strict_text(row["state"], "LEDGER_STATE"),
                    _strict_text(row["payload_hash"], "PAYLOAD_HASH", max_length=128),
                    _strict_text(row["outcome"], "LEDGER_OUTCOME"),
                ),
            )
        for row in outbox:
            exact_keys(row, {"operation_id", "envelope", "state"}, "OUTBOX_FIELDS")
            connection.execute(
                "INSERT INTO outbox VALUES(?,?,?)",
                (
                    _strict_text(row["operation_id"], "OPERATION_ID"),
                    _strict_blob(row["envelope"], "OUTBOX_ENVELOPE"),
                    _strict_text(row["state"], "OUTBOX_STATE"),
                ),
            )
        for row in drafts:
            exact_keys(row, {"draft_id", "document_id", "payload", "applied"}, "DRAFT_FIELDS")
            connection.execute(
                "INSERT INTO drafts VALUES(?,?,?,?)",
                (
                    _strict_text(row["draft_id"], "DRAFT_ID"),
                    _strict_text(row["document_id"], "DOCUMENT_ID"),
                    _strict_blob(row["payload"], "DRAFT_PAYLOAD"),
                    _strict_bool_int(row["applied"], "DRAFT_APPLIED"),
                ),
            )
        for row in signed_objects:
            exact_keys(row, {"object_id", "codec", "mandatory", "signed_bytes", "applied", "ack_state", "resigned"}, "SIGNED_FIELDS")
            connection.execute(
                "INSERT INTO signed_objects VALUES(?,?,?,?,?,?,?)",
                (
                    _strict_text(row["object_id"], "OBJECT_ID"),
                    _strict_text(row["codec"], "CODEC"),
                    _strict_bool_int(row["mandatory"], "MANDATORY"),
                    _strict_blob(row["signed_bytes"], "SIGNED_BYTES"),
                    _strict_bool_int(row["applied"], "SIGNED_APPLIED"),
                    _strict_text(row["ack_state"], "ACK_STATE"),
                    _strict_bool_int(row["resigned"], "RESIGNED"),
                ),
            )
        connection.execute(
            "INSERT INTO migration_seed VALUES(1,?,?)",
            (_strict_blob(seed_bytes, "SEED_BYTES"), _strict_blob(source_frontier, "SOURCE_FRONTIER")),
        )
        connection.execute(f"PRAGMA user_version={int(versions['store'])}")
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    os.chmod(db_path, 0o600)
    db_fd = os.open(db_path, os.O_RDONLY)
    try:
        os.fsync(db_fd)
    finally:
        os.close(db_fd)
    pointer = ActivePointer(generation, sha256_file(db_path), int(versions["store"]))
    _write_pointer(root, pointer)


def read_active_pointer(store_root: Path) -> ActivePointer:
    store_root = absolute_no_symlink(store_root, must_exist=True)
    if not store_root.is_dir():
        raise MigrationError("STORE_ROOT_INVALID")
    try:
        raw = read_strict_json(store_root / "ACTIVE.json", max_bytes=4096)
    except MigrationError as exc:
        raise MigrationError("ACTIVE_POINTER_INVALID") from exc
    if type(raw) is not dict or set(raw) != {"profile", "generation", "storeSha256", "storeVersion"}:
        raise MigrationError("ACTIVE_POINTER_INVALID")
    if raw["profile"] != ROOT_PROFILE:
        raise MigrationError("ACTIVE_POINTER_INVALID")
    generation = valid_generation(raw["generation"])
    digest = valid_sha(raw["storeSha256"], "ACTIVE_POINTER_INVALID")
    version = raw["storeVersion"]
    if type(version) is not int or type(version) is bool or version < 0:
        raise MigrationError("ACTIVE_POINTER_INVALID")
    return ActivePointer(generation, digest, version)


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(db_path.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise MigrationError("SOURCE_OPEN_FAILED") from exc


def inspect_database(db_path: Path, generation: str) -> SourceObservation:
    generation = valid_generation(generation)
    db_path = regular_file(db_path)
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(db_path) + suffix).exists():
            raise MigrationError("SOURCE_NOT_QUIESCENT")
    store_sha = sha256_file(db_path)
    connection = _readonly_connection(db_path)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("SOURCE_CORRUPT")
        row = connection.execute("SELECT * FROM store_metadata WHERE singleton=1").fetchone()
        if row is None:
            raise MigrationError("SOURCE_SCHEMA_INVALID")
        store_version = row["store_version"]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if store_version != SOURCE_STORE_VERSION or user_version != SOURCE_STORE_VERSION:
            raise MigrationError("UPGRADE_REQUIRED")
        versions = validate_versions(
            {
                "wire": row["wire_version"],
                "suite": row["suite_version"],
                "schema": row["schema_id"],
                "store": store_version,
                "sdk": row["sdk_version"],
                "ui": row["ui_version"],
            }
        )
        if row["generation"] != generation or versions["schema"] != SOURCE_SCHEMA_ID:
            raise MigrationError("SOURCE_SCHEMA_INVALID")
        if _schema_objects(connection) != expected_source_schema():
            raise MigrationError("SOURCE_SCHEMA_INVALID")
        inventory = {
            "operationLedger": connection.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0],
            "outbox": connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            "drafts": connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
            "signedObjects": connection.execute("SELECT COUNT(*) FROM signed_objects").fetchone()[0],
        }
        seed = connection.execute("SELECT seed_bytes,source_frontier FROM migration_seed WHERE singleton=1").fetchone()
        if seed is None or type(seed["seed_bytes"]) is not bytes or type(seed["source_frontier"]) is not bytes:
            raise MigrationError("SOURCE_SCHEMA_INVALID")
        seed_sha = sha256_bytes(seed["seed_bytes"])
        frontier_sha = sha256_bytes(seed["source_frontier"])
    except sqlite3.Error as exc:
        raise MigrationError("SOURCE_SCHEMA_INVALID") from exc
    finally:
        connection.close()
    identity = {
        "generation": generation,
        "storeSha256": store_sha,
        "versions": versions,
        "inventory": inventory,
        "seedSha256": seed_sha,
        "frontierSha256": frontier_sha,
    }
    return SourceObservation(
        generation=generation,
        store_sha256=store_sha,
        source_digest=sha256_bytes(canonical_bytes(identity)),
        source_size=db_path.stat().st_size,
        versions=versions,
        inventory=inventory,
        seed_sha256=seed_sha,
        frontier_sha256=frontier_sha,
        db_path=db_path,
    )


def inspect_generation(store_root: Path, generation: str) -> SourceObservation:
    store_root = absolute_no_symlink(store_root, must_exist=True)
    generation = valid_generation(generation)
    generation_root = absolute_no_symlink(store_root / "generations" / generation, must_exist=True)
    if not generation_root.is_dir():
        raise MigrationError("GENERATION_MISSING")
    return inspect_database(generation_root / "store.sqlite", generation)
