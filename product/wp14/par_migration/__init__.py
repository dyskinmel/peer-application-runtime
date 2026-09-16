"""Python/SQLite/POSIX local migration rehearsal candidate."""

from .backup import BackupManifest, create_verified_backup, migration_directory, require_verified_backup, verify_backup
from .errors import MigrationError
from .engine import MigrationResult, open_active_readonly, resume_migration, run_migration
from .journal import MigrationJournal
from .model import (
    CONVERTER_DIGEST,
    DEFAULT_VERSIONS,
    SOURCE_SCHEMA_ID,
    SOURCE_STORE_VERSION,
    TARGET_SCHEMA_ID,
    TARGET_STORE_VERSION,
    ActivePointer,
    MigrationPlan,
    SourceObservation,
)
from .planner import plan_migration
from .shadow import ShadowManifest, build_shadow, verify_shadow
from .store import create_v1_store, inspect_database, inspect_generation, read_active_pointer

__all__ = [
    "ActivePointer",
    "BackupManifest",
    "CONVERTER_DIGEST",
    "DEFAULT_VERSIONS",
    "MigrationError",
    "MigrationJournal",
    "MigrationResult",
    "MigrationPlan",
    "SOURCE_SCHEMA_ID",
    "SOURCE_STORE_VERSION",
    "ShadowManifest",
    "SourceObservation",
    "TARGET_SCHEMA_ID",
    "TARGET_STORE_VERSION",
    "create_v1_store",
    "create_verified_backup",
    "build_shadow",
    "inspect_database",
    "inspect_generation",
    "open_active_readonly",
    "migration_directory",
    "plan_migration",
    "read_active_pointer",
    "run_migration",
    "resume_migration",
    "require_verified_backup",
    "verify_backup",
    "verify_shadow",
]
