from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import MigrationError
from .fs import canonical_bytes, sha256_bytes

ROOT_PROFILE = "par-local-migration-root-0057"
PLAN_PROFILE = "par-local-migration-plan-0057"
SOURCE_SCHEMA_ID = "par-local-migration-v1"
TARGET_SCHEMA_ID = "par-local-migration-v2"
SOURCE_STORE_VERSION = 1
TARGET_STORE_VERSION = 2
SUPPORTED_CODECS = frozenset({"par.change.v1", "par.control.v1"})
CONVERTER_ID = "par-local-v1-to-v2-explicit-copy-0057"
CONVERTER_DIGEST = sha256_bytes(CONVERTER_ID.encode("ascii"))
VERSION_KEYS = ("wire", "suite", "schema", "store", "sdk", "ui")
DEFAULT_VERSIONS: dict[str, Any] = {
    "wire": "draft-2",
    "suite": "local-synthetic",
    "schema": SOURCE_SCHEMA_ID,
    "store": SOURCE_STORE_VERSION,
    "sdk": "0056",
    "ui": "0053",
}


def valid_generation(value: object) -> str:
    import re
    if type(value) is not str or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", value) is None:
        raise MigrationError("GENERATION_INVALID")
    return value


def valid_sha(value: object, code: str) -> str:
    import re
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MigrationError(code)
    return value


def validate_versions(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(VERSION_KEYS):
        raise MigrationError("VERSION_FIELDS")
    result = dict(value)
    for key in ("wire", "suite", "schema", "sdk", "ui"):
        if type(result[key]) is not str or not 1 <= len(result[key]) <= 96:
            raise MigrationError("VERSION_VALUE")
    if type(result["store"]) is not int or type(result["store"]) is bool or result["store"] < 0:
        raise MigrationError("VERSION_VALUE")
    return result


@dataclass(frozen=True)
class ActivePointer:
    generation: str
    store_sha256: str
    store_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": ROOT_PROFILE,
            "generation": self.generation,
            "storeSha256": self.store_sha256,
            "storeVersion": self.store_version,
        }


@dataclass(frozen=True)
class SourceObservation:
    generation: str
    store_sha256: str
    source_digest: str
    source_size: int
    versions: dict[str, Any]
    inventory: dict[str, int]
    seed_sha256: str
    frontier_sha256: str
    db_path: Path


@dataclass(frozen=True)
class MigrationPlan:
    store_root: Path
    work_root: Path
    observed_at: str
    source_generation: str
    source_store_sha256: str
    source_digest: str
    source_size: int
    versions: dict[str, Any]
    inventory: dict[str, int]
    seed_sha256: str
    frontier_sha256: str
    converter_digest: str
    target_store_version: int
    target_schema_id: str
    required_bytes: int
    available_bytes: int
    plan_digest: str
    migration_id: str
    target_generation: str

    def identity_dict(self) -> dict[str, Any]:
        return {
            "profile": PLAN_PROFILE,
            "sourceGeneration": self.source_generation,
            "sourceStoreSha256": self.source_store_sha256,
            "sourceDigest": self.source_digest,
            "sourceSize": self.source_size,
            "versions": dict(self.versions),
            "inventory": dict(self.inventory),
            "seedSha256": self.seed_sha256,
            "frontierSha256": self.frontier_sha256,
            "converterDigest": self.converter_digest,
            "targetStoreVersion": self.target_store_version,
            "targetSchemaId": self.target_schema_id,
            "requiredBytes": self.required_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_dict()
        value.update(
            {
                "storeRoot": str(self.store_root),
                "workRoot": str(self.work_root),
                "observedAt": self.observed_at,
                "availableBytes": self.available_bytes,
                "planDigest": self.plan_digest,
                "migrationId": self.migration_id,
                "targetGeneration": self.target_generation,
            }
        )
        return value

    @staticmethod
    def digest_identity(identity: dict[str, Any]) -> str:
        return sha256_bytes(canonical_bytes(identity))
