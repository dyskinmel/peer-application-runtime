import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicAlphaSmokeTests(unittest.TestCase):
    def test_wire_smoke_contract_passes_from_public_source(self):
        from tools.check_public_alpha_smoke import run_smoke

        report = run_smoke(ROOT)
        self.assertEqual(report['overall_result'], 'PASS', json.dumps(report, indent=2, sort_keys=True))
