"""Exercise the real status-only entrypoint, not a simulated conversion."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bank2odoo", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class EntrypointSmokeTests(unittest.TestCase):
    def test_launch_explicitly_disclaims_conversion(self) -> None:
        result = invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("foundation only", result.stdout)
        self.assertIn("not implemented", result.stdout)
        self.assertIn("No files were read", result.stdout)

    def test_version_identifies_foundation_not_a_converter(self) -> None:
        result = invoke("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.1.0 (foundation only)", result.stdout)

    def test_conversion_like_argument_fails_instead_of_pretending_success(self) -> None:
        result = invoke("--input", "nonexistent.xls")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_app_layers_import_without_gui_or_bank_io_dependencies(self) -> None:
        from bank2odoo import banks, core, reporting, ui, validation  # noqa: F401

        self.assertNotIn("PySide6", sys.modules)
