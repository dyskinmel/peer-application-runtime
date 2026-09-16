"""Run the public-alpha checks that can succeed from an extracted source archive."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# The development harness, store demo, and crypto provider checks deliberately
# remain nonclaims: they depend on excluded history, a macOS /var alias, and an
# unbundled provider pin respectively.  They are not archive acceptance checks.
SMOKE_COMMANDS = (
    ('wire-python', (sys.executable, 'tools/check_wire.py', '--suite', 'python')),
)


def run_smoke(root: Path) -> dict:
    results = []
    for name, command in SMOKE_COMMANDS:
        if not (root / command[1]).is_file():
            results.append({
                'name': name,
                'command': list(command),
                'result': 'BLOCKED',
                'reason': 'SOURCE_FILE_MISSING',
            })
            continue
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
        results.append({
            'name': name,
            'command': list(command),
            'exit_code': completed.returncode,
            'result': 'PASS' if completed.returncode == 0 else 'FAIL',
            'stdout': completed.stdout[-8192:],
            'stderr': completed.stderr[-8192:],
        })
    overall = (
        'PASS' if results and all(row['result'] == 'PASS' for row in results)
        else ('BLOCKED' if any(row['result'] == 'BLOCKED' for row in results) else 'FAIL')
    )
    return {'schema_version': 1, 'overall_result': overall, 'checks': results}
