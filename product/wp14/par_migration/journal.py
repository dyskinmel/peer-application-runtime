from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import MigrationError
from .fs import read_strict_json, write_json_atomic, write_json_exclusive
from .model import MigrationPlan

JOURNAL_PROFILE = "par-local-migration-journal-0057"
STAGES = (
    "PLANNED",
    "BACKUP_VERIFIED",
    "SHADOW_BUILT",
    "SHADOW_VERIFIED",
    "PUBLISHED",
    "ACTIVATED",
)


def _directory(plan: MigrationPlan) -> Path:
    return plan.work_root / plan.migration_id


@dataclass(frozen=True)
class MigrationJournal:
    plan_digest: str
    source_digest: str
    sequence: int
    stage: str

    def to_dict(self):
        return {
            "profile": JOURNAL_PROFILE,
            "planDigest": self.plan_digest,
            "sourceDigest": self.source_digest,
            "sequence": self.sequence,
            "stage": self.stage,
        }

    @classmethod
    def initialize(cls, plan: MigrationPlan) -> "MigrationJournal":
        from .backup import migration_directory
        directory = migration_directory(plan, create=True)
        plan_path = directory / "PLAN.json"
        if plan_path.exists():
            try:
                saved = read_strict_json(plan_path, max_bytes=1024 * 1024)
            except MigrationError as exc:
                raise MigrationError("PLAN_IDENTITY_MISMATCH") from exc
            if saved != plan.to_dict():
                raise MigrationError("PLAN_IDENTITY_MISMATCH")
        else:
            write_json_exclusive(plan_path, plan.to_dict())
        journal_path = directory / "JOURNAL.json"
        if journal_path.exists():
            return cls.load(plan)
        journal = cls(plan.plan_digest, plan.source_digest, 0, "PLANNED")
        write_json_exclusive(journal_path, journal.to_dict())
        return journal

    @classmethod
    def load(cls, plan: MigrationPlan) -> "MigrationJournal":
        path = _directory(plan) / "JOURNAL.json"
        if not path.is_file():
            raise MigrationError("JOURNAL_MISSING")
        try:
            raw = read_strict_json(path, max_bytes=16384)
        except MigrationError as exc:
            raise MigrationError("JOURNAL_INVALID") from exc
        if type(raw) is not dict or set(raw) != {"profile", "planDigest", "sourceDigest", "sequence", "stage"}:
            raise MigrationError("JOURNAL_INVALID")
        if raw["profile"] != JOURNAL_PROFILE or raw["planDigest"] != plan.plan_digest or raw["sourceDigest"] != plan.source_digest:
            raise MigrationError("JOURNAL_INVALID")
        if type(raw["sequence"]) is not int or type(raw["sequence"]) is bool or raw["sequence"] < 0:
            raise MigrationError("JOURNAL_INVALID")
        if raw["stage"] not in STAGES:
            raise MigrationError("JOURNAL_INVALID")
        return cls(raw["planDigest"], raw["sourceDigest"], raw["sequence"], raw["stage"])

    @classmethod
    def advance(cls, plan: MigrationPlan, target: str) -> "MigrationJournal":
        if target not in STAGES:
            raise MigrationError("JOURNAL_STAGE_INVALID")
        current = cls.load(plan)
        current_index = STAGES.index(current.stage)
        target_index = STAGES.index(target)
        if target_index <= current_index:
            return current
        if target_index != current_index + 1:
            raise MigrationError("JOURNAL_STAGE_INVALID")
        updated = cls(plan.plan_digest, plan.source_digest, current.sequence + 1, target)
        write_json_atomic(_directory(plan) / "JOURNAL.json", updated.to_dict())
        return updated
