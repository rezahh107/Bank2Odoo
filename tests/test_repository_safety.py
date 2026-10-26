"""Guard against accidentally tracking obviously private financial artifacts."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SEGMENTS = {"private", "data", "input", "inputs", "output", "outputs", "reports", "exports"}
PRIVATE_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".pdf", ".zip", ".7z", ".db", ".log"}


class RepositorySafetyTests(unittest.TestCase):
    def test_no_financial_documents_tracked(self) -> None:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        tracked = [Path(path.decode("utf-8")) for path in completed.stdout.split(b"\x00") if path]
        offenders = [
            str(path)
            for path in tracked
            if any(part.lower() in PRIVATE_SEGMENTS for part in path.parts)
            or path.suffix.lower() in PRIVATE_EXTENSIONS
        ]
        self.assertEqual(offenders, [], f"Private/financial artifacts tracked: {offenders}")
