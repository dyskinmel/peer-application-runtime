from __future__ import annotations

from contextlib import closing

import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from product.wp14.par_migration import (
    MigrationJournal,
    open_active_readonly,
    read_active_pointer,
    resume_migration,
)
from support import create_store_and_plan

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "tests/product/wp14_migration/migration_worker.py"
DEMO = ROOT / "examples/migration_rehearsal_demo.py"


class ProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name)
        self.store, self.work, self.plan = create_store_and_plan(self.base)

    def tearDown(self):
        self.td.cleanup()

    def kill_and_resume(self, stage: str):
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(WORKER),
            "--store-root",
            str(self.store),
            "--work-root",
            str(self.work),
            "--observed-at",
            self.plan.observed_at,
            "--kill-stage",
            stage,
            "--available-bytes",
            str(self.plan.available_bytes),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, -signal.SIGKILL, completed.stdout + completed.stderr)

        before = read_active_pointer(self.store)
        self.assertIn(before.generation, {self.plan.source_generation, self.plan.target_generation})
        with closing(open_active_readonly(self.store)) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)

        result = resume_migration(self.plan)
        self.assertTrue(result.activated)
        self.assertEqual(read_active_pointer(self.store).generation, self.plan.target_generation)
        self.assertEqual(MigrationJournal.load(self.plan).stage, "ACTIVATED")
        self.assertTrue((self.store / "generations" / self.plan.source_generation / "store.sqlite").is_file())
        self.assertFalse(list(self.store.glob(".ACTIVE.*.pending")))
        with closing(open_active_readonly(self.store)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_sigkill_backup_before_copy(self):
        self.kill_and_resume("backup.before_copy")

    def test_sigkill_backup_after_copy(self):
        self.kill_and_resume("backup.after_copy")

    def test_sigkill_shadow_after_rows(self):
        self.kill_and_resume("shadow.after_rows")

    def test_sigkill_after_shadow_verification(self):
        self.kill_and_resume("verify.after_shadow")

    def test_sigkill_switch_before_replace(self):
        self.kill_and_resume("switch.before_replace")

    def test_sigkill_switch_after_replace(self):
        self.kill_and_resume("switch.after_replace")

    def test_demo_reports_local_only_nonclaims(self):
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(DEMO)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["scope"], "LOCAL_PYTHON_SQLITE_POSIX_MIGRATION_REHEARSAL_ONLY")
        self.assertEqual(report["activeStoreVersion"], 2)
        self.assertEqual(report["egressAttempts"], 0)
        self.assertFalse(report["nativeBuildExecuted"])
        self.assertFalse(report["deviceVerified"])
        self.assertFalse(report["physicalPowerLossTested"])
        self.assertFalse(report["g9Qualified"])
        self.assertFalse(report["productQualified"])


if __name__ == "__main__":
    unittest.main()
