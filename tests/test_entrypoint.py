"""Entrypoint smoke: headless engine exists, desktop GUI does not."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "bank2odoo", *args],
                          cwd=ROOT, capture_output=True, text=True, check=False)

class EntrypointSmokeTests(unittest.TestCase):
    def test_no_args_honestly_reports_gui_unavailable(self) -> None:
        result = invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("headless", result.stdout)
        self.assertIn("GUI is NOT implemented", result.stdout)
        self.assertIn("No bank file processed", result.stdout)

    def test_version_no_longer_claims_foundation_only(self) -> None:
        result = invoke("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.2.0 (headless candidate engine)", result.stdout)

    def test_partial_conversion_arguments_fail(self) -> None:
        result = invoke("--input", "nonexistent.xls")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --input", result.stderr)

    def test_app_layers_import_without_gui(self) -> None:
        # Assert import isolation in a fresh interpreter, independent of the
        # order in which unrelated GUI test modules were imported by unittest.
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys; from bank2odoo import banks, core, reporting, ui, validation; "
             "from bank2odoo.core.engine import convert; "
             "assert 'PySide6' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(probe.returncode, 0, probe.stderr)
