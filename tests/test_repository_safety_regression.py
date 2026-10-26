"""Black-box regression of Git privacy enforcement in disposable repositories."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_repository_safety import ROOT, forbidden_tracked_paths


class PrivacyGuardRegressionTests(unittest.TestCase):
    def make_repo(self, directory: Path, extra_ignore: str = "") -> None:
        (directory / "tests").mkdir()
        ignore = (ROOT / ".gitignore").read_bytes()
        (directory / ".gitignore").write_bytes(ignore + extra_ignore.encode("utf-8"))
        shutil.copyfile(
            ROOT / "tests/test_repository_safety.py",
            directory / "tests/test_repository_safety.py",
        )
        subprocess.run(["git", "init", "-q"], cwd=directory, check=True, capture_output=True)
        subprocess.run(
            ["git", "add", "--", ".gitignore", "tests/test_repository_safety.py"],
            cwd=directory, check=True, capture_output=True,
        )

    def add_synthetic(self, directory: Path, path: str, force: bool = False) -> None:
        destination = directory / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("Synthetic fixture, no financial information.\n", encoding="utf-8")
        command = ["git", "add", "-f"] if force else ["git", "add"]
        subprocess.run(command + ["--", path], cwd=directory, check=True, capture_output=True)

    def run_guard(self, directory: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests",
             "-p", "test_repository_safety.py", "-v"],
            cwd=directory, capture_output=True, text=True, check=False,
        )

    def test_force_tracked_privacy_cases_fail_the_actual_guard(self) -> None:
        for path in (
            ".env", "leaked.sqlite3", "tmp/control.txt", "reports/control.txt",
            "leaked.xlsx", "uppercase.XLSX",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_repo(root)
                self.add_synthetic(root, path, force=True)
                result = self.run_guard(root)
                self.assertNotEqual(result.returncode, 0, f"Missed {path}: {result.stdout}")
                # unittest prints repr(list[str]); Windows paths contain escaped backslashes.
                self.assertIn(repr(str(Path(path))), result.stderr)

    def test_new_ignore_rule_enforced_without_classifier_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root, extra_ignore="\n*.new-private-format\n")
            path = "statement.new-private-format"
            self.add_synthetic(root, path, force=True)
            result = self.run_guard(root)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(path, result.stderr)

    def test_allowed_source_and_env_example_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            self.add_synthetic(root, "src/allowed.py")
            self.add_synthetic(root, ".env.example")
            result = self.run_guard(root)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_ls_files_failure_is_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("*.csv\n", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                forbidden_tracked_paths(root)

    def test_git_check_ignore_failure_is_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            real_run = subprocess.run

            def simulate_git_failure(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                if args[:2] == ["git", "check-ignore"]:
                    self.assertIn("--no-index", args)
                    return subprocess.CompletedProcess(args, 128, b"", b"synthetic Git failure")
                return real_run(args, **kwargs)

            with mock.patch("test_repository_safety.subprocess.run", side_effect=simulate_git_failure):
                with self.assertRaisesRegex(RuntimeError, "git check-ignore failed"):
                    forbidden_tracked_paths(root)

    def test_missing_tracked_gitignore_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            subprocess.run(
                ["git", "rm", "--cached", ".gitignore"],
                cwd=root, check=True, capture_output=True,
            )
            with self.assertRaisesRegex(RuntimeError, ".gitignore must be tracked"):
                forbidden_tracked_paths(root)
