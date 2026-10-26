"""Fail if Git tracks paths forbidden by repository ignore or privacy policy."""

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Additional stricter case-insensitive privacy categories, not a copy of .gitignore.
PRIVATE_SEGMENTS = {"private", "data", "input", "inputs", "output", "outputs", "reports", "exports"}
PRIVATE_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".pdf", ".zip", ".7z", ".db", ".log"}


def forbidden_tracked_paths(root: Path) -> list[str]:
    """Use Git's own ignores even for force-added index entries; fail closed on errors."""
    if not (root / ".gitignore").is_file():
        raise RuntimeError("Repository .gitignore is missing; cannot verify privacy policy")

    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    tracked_paths = [path for path in tracked.split(b"\0") if path]
    if b".gitignore" not in tracked_paths:
        raise RuntimeError("Repository .gitignore must be tracked to enforce privacy policy")

    # Without --no-index, check-ignore skips force-tracked files entirely.
    checked = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=root,
        input=tracked,
        capture_output=True,
        check=False,
    )
    # Git uses 1 to mean "no ignored paths", not a command failure.
    if checked.returncode not in (0, 1) or checked.stderr:
        raise RuntimeError(
            f"git check-ignore failed (exit {checked.returncode}): "
            f"{os.fsdecode(checked.stderr)}"
        )
    if (checked.returncode == 0) != bool(checked.stdout):
        raise RuntimeError("git check-ignore returned an inconsistent match result")

    ignored = set(checked.stdout.split(b"\0")) - {b""}
    offending = []
    for raw_path in tracked_paths:
        path = Path(os.fsdecode(raw_path))
        if (
            raw_path in ignored
            or any(part.lower() in PRIVATE_SEGMENTS for part in path.parts)
            or path.suffix.lower() in PRIVATE_EXTENSIONS
        ):
            offending.append(str(path))
    return sorted(offending)


class RepositorySafetyTests(unittest.TestCase):
    def test_no_financial_documents_tracked(self) -> None:
        self.assertEqual(
            forbidden_tracked_paths(ROOT),
            [],
            "Paths ignored by Git or forbidden by the stricter privacy policy are tracked",
        )
