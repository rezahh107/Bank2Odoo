"""Synthetic disk-level qualification of report-first paired publication outcomes.

No real statements or private report contents are committed or uploaded.
These tests exercise the production save_candidate path, including filesystem
fault injection, not a reimplementation of its write algorithm.
"""
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import tempfile

from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting import output
from bank2odoo.reporting.output import (
    SavePublicationError, control_report, output_csv, save_candidate,
)
from bank2odoo.validation.financial import StatementError
from tests.test_conversion import write_mellat


class SavePublicationOutcomeTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "نمونه_آزمایشی.csv"
        write_mellat(self.source, [
            ["1", "1405/07/01", "10:00:00", "01", "واریز ساختگی", "0", "100", "100"],
        ])
        self.same = convert(self.source, Context("IRR", "IRR"))
        self.converted = convert(
            self.source, Context("IRR", "TOMAN", approved_factor=Decimal("0.1"))
        )
        self.folder = self.root / "خروجی خصوصی"
        self.folder.mkdir()

    def pair(self, result=None, folder=None):
        result = result or self.same
        folder = folder or self.folder
        prefix = f"Bank2Odoo_{self.source.stem}_{result.sha256[:10]}"
        # The real GUI sanitizes unsafe chars; this stem contains only
        # alphanumeric/underscore, so it generates these exact names.
        return (folder / f"{prefix}_candidate.csv",
                folder / f"{prefix}_control.txt")

    def state(self, folder=None):
        folder = folder or self.folder
        return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}

    def assert_complete(self, result=None, folder=None):
        result = result or self.same
        csv_path, report_path = self.pair(result, folder)
        self.assertEqual(csv_path.read_bytes(), output_csv(result).encode("utf-8"))
        self.assertEqual(report_path.read_bytes(), control_report(result).encode("utf-8"))
        self.assertIn(b"Date,Label,Amount", csv_path.read_bytes())
        self.assertEqual(len(list((folder or self.folder).glob(".bank2odoo-*.tmp"))), 0)

    def test_first_save_duplicate_and_same_source_different_valid_context(self):
        csv_path, report_path = self.pair()
        before = self.state()
        self.assertEqual(before, {})
        save_candidate(self.same, csv_path, report_path)
        self.assert_complete()
        original = self.state()
        self.assertEqual(self.same.sha256, self.converted.sha256)
        self.assertNotEqual(output_csv(self.same), output_csv(self.converted))
        self.assertNotEqual(control_report(self.same), control_report(self.converted))
        self.assertEqual(self.pair(self.same), self.pair(self.converted))
        for candidate in (self.same, self.converted):
            with self.assertRaisesRegex(StatementError, "not already exist"):
                save_candidate(candidate, *self.pair(candidate))
            self.assertEqual(self.state(), original, "Existing outputs modified")
        self.assertNotEqual(original, before)

    def test_csv_only_report_only_and_complete_pair_are_never_replaced(self):
        for existing in ("csv", "report", "pair"):
            with self.subTest(existing=existing):
                folder = self.root / existing
                folder.mkdir()
                csv_path, report_path = self.pair(folder=folder)
                if existing in ("csv", "pair"):
                    csv_path.write_bytes(b"existing CSV bytes")
                if existing in ("report", "pair"):
                    report_path.write_bytes(b"existing private report bytes")
                before = self.state(folder)
                with self.assertRaises(StatementError):
                    save_candidate(self.same, csv_path, report_path)
                self.assertEqual(self.state(folder), before)

    def test_missing_and_forbidden_checkout(self):
        csv_path, report_path = self.pair(folder=self.root / "missing")
        with self.assertRaisesRegex(StatementError, "same existing private directory"):
            save_candidate(self.same, csv_path, report_path)
        self.assertFalse(csv_path.exists())
        self.assertFalse(report_path.exists())
        checkout = Path(output.__file__).resolve().parents[2]
        with self.assertRaisesRegex(StatementError, "outside the public source checkout"):
            save_candidate(self.same, checkout / "synthetic.csv", checkout / "synthetic.txt")

    def test_first_link_permission_denied_no_final_or_temp(self):
        with patch.object(output.os, "link", side_effect=PermissionError("synthetic access denied")):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(captured.exception.outcome, "NO_FINALS")
        self.assertIsInstance(captured.exception.__cause__, PermissionError)
        self.assertEqual(self.state(), {})

    def test_second_link_failure_retains_report_and_cleans_temps(self):
        actual = output.os.link
        calls = []
        def fail_second(src, dst):
            calls.append(dst.name)
            if len(calls) == 2:
                raise OSError("synthetic second-link fault")
            return actual(src, dst)
        with patch.object(output.os, "link", side_effect=fail_second):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(calls, [self.pair()[1].name, self.pair()[0].name])
        self.assertEqual(captured.exception.outcome, "PARTIAL")
        self.assertIn("second-link fault", str(captured.exception.__cause__))
        csv_path, report_path = self.pair()
        self.assertFalse(csv_path.exists())
        self.assertEqual(report_path.read_bytes(), control_report(self.same).encode("utf-8"))
        self.assertEqual(len(list(self.folder.glob(".bank2odoo-*.tmp"))), 0)

    def test_failed_publication_never_attempts_final_file_unlink(self):
        actual_link = output.os.link
        actual_unlink = Path.unlink
        count = 0
        report_path = self.pair()[1].resolve()
        def second_link_fails(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("primary synthetic publish fault")
            return actual_link(src, dst)
        def forbid_final_unlink(path, *args, **kwargs):
            if path == report_path:
                self.fail("Final output unlink must never be attempted")
            return actual_unlink(path, *args, **kwargs)
        with patch.object(output.os, "link", side_effect=second_link_fails), \
             patch.object(Path, "unlink", autospec=True, side_effect=forbid_final_unlink):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(captured.exception.outcome, "PARTIAL")
        self.assertIn("primary synthetic publish fault", str(captured.exception.__cause__))
        self.assertFalse(self.pair()[0].exists())
        self.assertEqual(report_path.read_bytes(), control_report(self.same).encode("utf-8"))
        self.assertEqual(len(list(self.folder.glob(".bank2odoo-*.tmp"))), 0)

    def test_published_report_replaced_by_independent_writer_survives_failure(self):
        """Deterministic P0 regression: published pathname != current ownership."""
        actual_link = output.os.link
        csv_path, report_path = self.pair()
        external = b"independent replacement - must survive"
        calls = []
        def replace_between_links(src, dst):
            calls.append(Path(dst))
            if len(calls) == 1:
                actual_link(src, dst)
                return
            report_path.unlink()
            report_path.write_bytes(external)
            raise OSError("synthetic second-link failure after replacement")
        with patch.object(output.os, "link", side_effect=replace_between_links):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, csv_path, report_path)
        self.assertEqual(calls, [report_path.resolve(), csv_path.resolve()])
        self.assertEqual(report_path.read_bytes(), external)
        self.assertFalse(csv_path.exists())
        self.assertEqual(captured.exception.outcome, "AMBIGUOUS")
        self.assertIn("second-link failure", str(captured.exception.__cause__))
        self.assertFalse(captured.exception.cleanup_failed)
        self.assertEqual(len(list(self.folder.glob(".bank2odoo-*.tmp"))), 0)

    def test_cleanup_failure_after_complete_pair_is_not_false_no_outputs(self):
        actual_unlink = Path.unlink
        failed = False
        def cleanup_fails_once(path, *args, **kwargs):
            nonlocal failed
            if path.name.startswith(".bank2odoo-") and not failed:
                failed = True
                raise PermissionError("synthetic temporary cleanup denied")
            return actual_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", autospec=True, side_effect=cleanup_fails_once):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(captured.exception.outcome, "COMPLETE_PAIR")
        self.assertTrue(captured.exception.cleanup_failed)
        self.assertIsInstance(captured.exception.__cause__, PermissionError)
        csv_path, report_path = self.pair()
        self.assertEqual(csv_path.read_bytes(), output_csv(self.same).encode("utf-8"))
        self.assertEqual(report_path.read_bytes(), control_report(self.same).encode("utf-8"))
        residuals = list(self.folder.glob(".bank2odoo-*.tmp"))
        self.assertEqual(len(residuals), 1, "Cleanup fault must be observable")
        for path in residuals:
            path.unlink()

    def test_unexpected_unowned_final_is_ambiguous_not_deleted(self):
        actual = output.os.link
        count = 0
        def external_race(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                dst.write_bytes(b"other writer; do not delete")
                raise OSError("synthetic ambiguous second-link race")
            return actual(src, dst)
        with patch.object(output.os, "link", side_effect=external_race):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(captured.exception.outcome, "AMBIGUOUS")
        self.assertEqual(self.pair()[1].read_bytes(), control_report(self.same).encode("utf-8"))
        self.assertEqual(self.pair()[0].read_bytes(), b"other writer; do not delete")
        self.assertEqual(len(list(self.folder.glob(".bank2odoo-*.tmp"))), 0)

    def test_first_link_failure_and_cleanup_failure_keep_originating_error(self):
        original_unlink = Path.unlink
        def temp_unlink_fails(path, *args, **kwargs):
            if path.name.startswith(".bank2odoo-"):
                raise PermissionError("synthetic temp residual")
            return original_unlink(path, *args, **kwargs)
        with patch.object(output.os, "link", side_effect=OSError("primary first link")), \
             patch.object(Path, "unlink", autospec=True, side_effect=temp_unlink_fails):
            with self.assertRaises(SavePublicationError) as captured:
                save_candidate(self.same, *self.pair())
        self.assertEqual(captured.exception.outcome, "NO_FINALS")
        self.assertTrue(captured.exception.cleanup_failed)
        self.assertIn("primary first link", str(captured.exception.__cause__))
        self.assertEqual(len(list(self.folder.glob(".bank2odoo-*.tmp"))), 2)
        self.assertFalse(self.pair()[0].exists())
        self.assertFalse(self.pair()[1].exists())
        for path in self.folder.glob(".bank2odoo-*.tmp"):
            path.unlink()

    def test_unicode_folder_and_practical_nested_path(self):
        long_folder = self.root / ("پوشه_آزمایشی_" + "الف" * 18) / ("nested_" + "x" * 30)
        long_folder.mkdir(parents=True)
        save_candidate(self.same, *self.pair(folder=long_folder))
        self.assert_complete(folder=long_folder)
