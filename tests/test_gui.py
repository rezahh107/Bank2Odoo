"""Offscreen Qt interaction + real financial engine + paired-save regression.

Uses fictional statements only. This is not an accountant Windows acceptance test.
"""
import csv
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bank2odoo.ui.window import MainWindow, _Job, human_error
from bank2odoo.core.engine import Context
from threading import Event
from hashlib import sha256
from unittest.mock import patch
from bank2odoo.core.engine import convert as actual_convert
from bank2odoo.banks.reader import read_statement as actual_read_statement
from bank2odoo.reporting.output import save_candidate as actual_save_candidate

HEADER = [
    "ردیف", "تاریخ", "زمان", "شماره سریال", "شرح", "مبلغ گردش بدهکار",
    "مبلغ گردش بستانکار", "مانده", "واریز کننده/ذینفع",
]


def statement(path: Path, *, not_proven: bool = False, duplicate: bool = False) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Fictional test data — not a bank statement"])
        writer.writerow(HEADER)
        if duplicate:
            writer.writerow(["1", "1405/07/01", "10:00", "10", "هزینه تست", "25", "0", ""])
            writer.writerow(["2", "1405/07/01", "10:00", "10", "هزینه تست", "25", "0", ""])
        else:
            writer.writerow(["1", "1405/07/01", "10:00", "A1", "واریز آزمایشی", "0", "100", "100"])
            writer.writerow(["2", "1405/07/02", "11:00", "A2", "کارمزد آزمایشی", "25", "0",
                             "" if not_proven else "75"])


class AccountantUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        self.source = self.private / "fictional.csv"
        statement(self.source)
        self.window = MainWindow()
        self.window.show()
        self.addCleanup(self.window.close)
        self.app.processEvents()

    def _wait_operation(self, signal) -> None:
        if self.window._thread is None:
            return
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        signal.connect(loop.quit)
        timeout.start(12000)
        loop.exec()
        self.assertTrue(timeout.isActive(), "Qt background operation timed out")
        self.assertIsNone(self.window._thread, "worker lifecycle not finalized")

    def _select(self, path: Path) -> None:
        self.window.set_source(path)
        self._wait_operation(self.window.detection_done)

    def _save(self) -> None:
        self.window.save_files()
        self._wait_operation(self.window.save_done)

    def _approve(self, source="IRR", target="IRR", factor=None) -> None:
        self.window.source_unit.setCurrentIndex(
            self.window.source_unit.findData(source)
        )
        self.window.target_unit.setCurrentIndex(
            self.window.target_unit.findData(target)
        )
        self.window.journal.setText("ژورنال فرضی")
        self.window.precision.setValue(0)
        if factor is not None:
            self.window.factor.setText(factor)
        self.window.approved.setChecked(True)

    def _wait_conversion(self) -> None:
        if self.window._thread is not None:
            loop = QEventLoop()
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            self.window.conversion_done.connect(loop.quit)
            timeout.start(12000)
            loop.exec()
            self.assertTrue(timeout.isActive(), "Qt conversion worker timed out")
        # The terminal result signal can precede QThread.finished by one event turn.
        for _ in range(100):
            self.app.processEvents()
            if self.window._thread is None:
                break
            QTest.qWait(10)
        self.assertIsNone(self.window._thread, "worker did not clean up")

    def _convert(self):
        self._select(self.source)
        self._approve()
        self.window.start_conversion()
        self._wait_conversion()
        self.assertIsNotNone(self.window.result)
        return self.window.result

    def test_visible_persian_workflow_and_directionality(self):
        self.assertEqual(self.window.layoutDirection(), Qt.LayoutDirection.RightToLeft)
        self.assertIn("Odoo", self.window.status.parent().window().windowTitle() or "Odoo")
        self.assertEqual(self.window.path_field.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.assertEqual(self.window.output_directory.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.assertTrue(self.window.select_button.isEnabled())
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertTrue(self.window.convert_button.text())
        self.assertTrue(self.window.approved.text())
        self.window.select_button.setFocus()
        self.assertTrue(self.window.select_button.hasFocus())
        QTest.keyClick(self.window.select_button, Qt.Key.Key_Tab)
        self.assertIsNotNone(self.app.focusWidget())

    def test_detection_by_content_not_filename_and_unsupported_file(self):
        disguised = self.private / "not_really_a_bank.xls"
        statement(disguised)
        self._select(disguised)
        self.assertIn("بانک ملت", self.window.detected.text())
        self.assertEqual(self.window.source, disguised)
        wrong = self.private / "bad.csv"
        wrong.write_text("name,total\nfoo,1\n", encoding="utf-8")
        self._select(wrong)
        self.assertIsNone(self.window.source)
        self.assertIn("شناسایی نشد", self.window.detected.text())
        self.assertFalse(self.window.save_button.isEnabled())

    def test_conversion_blocks_missing_context_or_approval(self):
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self._select(self.source)
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self._approve()
        self.window.approved.setChecked(False)
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.window.approved.setChecked(True)
        self.window.journal.clear()  # invalidates previous approval
        self.assertFalse(self.window.approved.isChecked())
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)

    def test_cross_unit_requires_explicit_valid_factor(self):
        self._select(self.source)
        self._approve(source="TOMAN", target="IRR")
        self.assertTrue(self.window.factor.isEnabled())
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.assertIsNone(self.window.result)
        self.window.factor.setText("11")
        self.window.approved.setChecked(True)
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.window.factor.setText("10")
        self.window.approved.setChecked(True)
        self.window.start_conversion()
        self._wait_conversion()
        result = self.window.result
        self.assertIsNotNone(result)
        self.assertEqual(str(result.rows[0].converted), "1000")
        self.assertEqual(result.factor, 10)

    def test_melli_legacy_xls_ui_to_private_pair(self):
        import xlwt  # Existing test-only BIFF8 writer; no real bank data.

        path = self.private / "fictional_melli.xls"
        workbook = xlwt.Workbook(encoding="utf-8")
        sheet = workbook.add_sheet("Fictional")
        headers = ["ردیف", "تاریخ", "زمان", "نوع", "مبلغ", "شماره پیگیری",
                   "اطلاعات تکمیلی", "شرح", "توضیحات", "مانده"]
        for column, label in enumerate(headers):
            sheet.write(0, column, label)
        movements = [
            ["2", "1405/07/02", "11:00:00", "برداشت", "25", "F-2", "",
             "کارمزد ساختگی", "", "75"],
            ["1", "1405/07/01", "10:00:00", "واریز", "100", "F-1", "",
             "واریز ساختگی", "", "100"],
        ]
        for row_index, movement in enumerate(movements, 1):
            for column, value in enumerate(movement):
                sheet.write(row_index, column, value)
        workbook.save(str(path))

        self._select(path)
        self.assertIn("بانک ملی", self.window.detected.text())
        self.assertIn("2 گردش", self.window.detected.text())
        self._approve()
        self.window.start_conversion()
        self._wait_conversion()
        result = self.window.result
        self.assertIsNotNone(result)
        self.assertEqual(result.bank, "melli")
        self.assertTrue(result.balance_status.startswith("PASS"))
        self.assertEqual(len(result.rows), 2)
        self.window.output_directory.setText(str(self.private))
        self._save()
        outputs = list(self.private.glob("Bank2Odoo_*"))
        self.assertEqual(len(outputs), 2)
        csv_path = next(item for item in outputs if item.name.endswith("_candidate.csv"))
        report_path = next(item for item in outputs if item.name.endswith("_control.txt"))
        self.assertEqual(csv_path.read_text(encoding="utf-8"),
                         "Date,Label,Amount\n"
                         "2026-09-24,کارمزد ساختگی,-25\n"
                         "2026-09-23,واریز ساختگی,100\n")
        self.assertIn("Source rows: 2", report_path.read_text(encoding="utf-8"))
        self.assertIn("دو فایل ایجاد شدند", self.window.saved_paths.text())

    def test_success_pass_exact_csv_private_report_and_no_overwrite(self):
        result = self._convert()
        self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
        self.assertEqual(len(result.rows), 2)
        self.assertIn("منطبق", self.window.summary.text())
        self.assertIn("75", self.window.summary.text())
        self.assertIn("نامزد بررسی", self.window.status.text())
        self.window.output_directory.setText(str(self.private))
        self._save()
        paths = list(self.private.glob("Bank2Odoo_*"))
        self.assertEqual(len(paths), 2)
        csv_path = next(x for x in paths if x.suffix == ".csv")
        report_path = next(x for x in paths if x.suffix == ".txt")
        self.assertEqual(csv_path.read_text(encoding="utf-8"),
                         "Date,Label,Amount\n"
                         "2026-09-23,واریز آزمایشی,100\n"
                         "2026-09-24,کارمزد آزمایشی,-25\n")
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("PRIVATE accountant control report", report)
        self.assertIn('"csv_row": 2', report)
        self.assertIn("REVIEW CANDIDATE ONLY", report)
        self.assertIn(str(csv_path), self.window.saved_paths.text())
        self.assertIn(str(report_path), self.window.saved_paths.text())
        self.assertFalse(self.window.save_button.isEnabled())
        self._save()
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)

    def test_not_proven_is_not_failure_and_duplicate_is_retained(self):
        statement(self.source, not_proven=True)
        result = self._convert()
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN"))
        self.assertIn("احراز نشده", self.window.summary.text())
        self.assertNotIn("خطا:", self.window.status.text())
        statement(self.source, duplicate=True)
        self._select(self.source)
        self._approve()
        self.window.start_conversion()
        self._wait_conversion()
        self.assertEqual(len(self.window.result.rows), 2)
        self.assertTrue(any("duplicate" in x.lower() for x in self.window.result.issues))
        self.assertIn("حذف نشده", self.window.summary.text())

    def test_change_after_conversion_invalidates_candidate(self):
        self._convert()
        self.assertTrue(self.window.save_button.isEnabled())
        self.window.journal.setText("ژورنال تغییرکرده")
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())

    def test_save_invalid_directory_and_collision_fail_cleanly(self):
        self._convert()
        self._save()
        self.assertIn("پوشه خصوصی", self.window.status.text())
        not_folder = self.private / "missing"
        self.window.output_directory.setText(str(not_folder))
        self._save()
        self.assertIn("خطای ذخیره", self.window.status.text())
        self.assertFalse(list(self.private.glob("Bank2Odoo_*")))
        # Manually pre-existing private name is not replaced and partner not created.
        self.window.output_directory.setText(str(self.private))
        prefix = f"Bank2Odoo_{self.source.stem}_{self.window.result.sha256[:10]}"
        report = self.private / f"{prefix}_control.txt"
        report.write_text("keep", encoding="utf-8")
        self._save()
        self.assertEqual(report.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.private / f"{prefix}_candidate.csv").exists())
        self.assertIn("هم‌نام", self.window.status.text())

    def test_failed_conversion_does_not_enable_save(self):
        self._select(self.source)
        self._approve()
        # The file changed after content detection; actual convert re-reads and rejects.
        self.source.write_text("invalid", encoding="utf-8")
        self.window.start_conversion()
        self._wait_conversion()
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIn("خطا", self.window.status.text())
        self.assertTrue(self.window.details_button.isCheckable())
        self.window.details_button.setChecked(True)
        self.assertTrue(self.window.details.isVisible())

    def test_cancelled_worker_never_emits_a_result(self):
        stop = Event()
        stop.set()
        state = {"kind": "convert", "value": None, "error": None, "cancelled": False}
        worker = _Job("convert", state, path=self.source,
                      context=Context("IRR", "IRR", "Synthetic"), stop=stop)
        done = []
        worker.finished.connect(lambda: done.append(True))
        worker.execute()
        self.assertEqual(done, [True])
        self.assertTrue(state["cancelled"])
        self.assertIsNone(state["value"])
        self.assertIsNone(self.window.result)

    def test_user_stop_during_worker_discards_result(self):
        self._select(self.source)
        self._approve()
        entered, released = Event(), Event()

        def delayed(path, context):
            entered.set()
            if not released.wait(6):
                raise RuntimeError("test release not signalled")
            return actual_convert(path, context)

        with patch("bank2odoo.ui.window.convert", side_effect=delayed):
            self.window.start_conversion()
            self.assertTrue(entered.wait(6), "conversion worker never entered")
            self.assertTrue(self.window.cancel_button.isEnabled())
            self.window.cancel_conversion()
            released.set()
            self._wait_conversion()
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIn("توقف", self.window.status.text())

    def test_reselect_valid_statement_revokes_prior_approval(self):
        self._select(self.source)
        self._approve()
        self.assertTrue(self.window.approved.isChecked())
        old_digest = self.window._approved_digest
        other = self.private / "other_fictional.csv"
        statement(other, not_proven=True)
        self._select(other)
        self.assertNotEqual(self.window._selected_digest, old_digest)
        self.assertIsNone(self.window._approved_digest)
        self.assertFalse(self.window.approved.isChecked())
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.assertIsNone(self.window.result)
        self._approve()
        self.window.start_conversion()
        self._wait_conversion()
        self.assertIsNotNone(self.window.result)

    def test_failed_selection_and_missing_context_revoke_approval(self):
        self._select(self.source)
        self._approve()
        wrong = self.private / "bad.csv"
        wrong.write_text("invalid statement", encoding="utf-8")
        self._select(wrong)
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window.source)
        self.assertIsNone(self.window._selected_digest)
        self.assertIsNone(self.window._approved_digest)
        self.window.approved.setChecked(True)
        self.assertFalse(self.window.approved.isChecked())
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self._select(self.source)
        self._approve()
        self.window.source_unit.setCurrentIndex(0)
        self.assertFalse(self.window.approved.isChecked())
        self.window.approved.setChecked(True)
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.assertIsNone(self.window.result)

    def test_mutated_valid_source_digest_rejected_after_conversion(self):
        self._select(self.source)
        self._approve()
        selected_digest = self.window._selected_digest
        self.assertEqual(selected_digest, sha256(self.source.read_bytes()).hexdigest())
        statement(self.source, duplicate=True)  # Still valid, different exact bytes
        self.window.start_conversion()
        self._wait_conversion()
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIsNone(self.window._selected_digest)
        self.assertIsNone(self.window._approved_digest)
        self.assertFalse(self.window.approved.isChecked())
        self.assertIn("تغییر", self.window.status.text())
        self.window.approved.setChecked(True)
        self.assertFalse(self.window.approved.isChecked())
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self._select(self.source)
        self._approve()
        self.window.start_conversion()
        self._wait_conversion()
        self.assertEqual(len(self.window.result.rows), 2)

    def test_slow_detection_is_background_and_rejects_overlaps(self):
        original = actual_read_statement
        entered, released = Event(), Event()
        work_on_foreign_thread = []

        def delayed(path, raw):
            work_on_foreign_thread.append(QThread.currentThread() != self.window.thread())
            entered.set()
            if not released.wait(6):
                raise RuntimeError("detection release timeout")
            return original(path, raw)

        with patch("bank2odoo.ui.window.read_statement", side_effect=delayed):
            self.window.set_source(self.source)
            try:
                self.assertTrue(entered.wait(6))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.app.processEvents()
                self.assertEqual(ticks, [True])
                self.assertEqual(work_on_foreign_thread, [True])
                self.assertIsNotNone(self.window._thread)
                self.window.start_conversion()
                self.assertIsNone(self.window.result)
                self.window.set_source(self.private / "overlap.csv")
                self.assertEqual(self.window.path_field.text(), str(self.source))
                with patch("bank2odoo.ui.window.QMessageBox.information"):
                    self.assertFalse(self.window.close())
                self.assertTrue(self.window.isVisible())
            finally:
                released.set()
            self._wait_operation(self.window.detection_done)
        self.assertEqual(self.window.source, self.source)
        self.assertEqual(self.window._selected_digest,
                         sha256(self.source.read_bytes()).hexdigest())

    def test_slow_paired_save_is_background_noncancellable_and_nonoverlapping(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        entered, released = Event(), Event()
        foreign = []

        def delayed(result, csv_path, report_path):
            foreign.append(QThread.currentThread() != self.window.thread())
            entered.set()
            if not released.wait(6):
                raise RuntimeError("save release timeout")
            return actual_save_candidate(result, csv_path, report_path)

        with patch("bank2odoo.ui.window.save_candidate", side_effect=delayed):
            self.window.save_files()
            try:
                self.assertTrue(entered.wait(6))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.app.processEvents()
                self.assertEqual(ticks, [True])
                self.assertEqual(foreign, [True])
                self.window.save_files()
                self.window.start_conversion()
                self.window.set_source(self.private / "different.csv")
                self.window.cancel_conversion()  # Does not cancel atomic save.
                self.assertEqual(self.window.path_field.text(), str(self.source))
                with patch("bank2odoo.ui.window.QMessageBox.information"):
                    self.assertFalse(self.window.close())
                self.assertEqual(list(self.private.glob("Bank2Odoo_*")), [])
            finally:
                released.set()
            self._wait_operation(self.window.save_done)
        self.assertIn("دو فایل ایجاد شدند", self.window.saved_paths.text())
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)
        self.assertFalse(self.window.save_button.isEnabled())

    def test_async_save_failure_and_stale_finished_slot_never_publish_success(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        with patch("bank2odoo.ui.window.save_candidate",
                   side_effect=OSError("synthetic failure")):
            self._save()
        self.assertIn("خطای ذخیره", self.window.status.text())
        self.assertNotIn("دو فایل ایجاد شدند", self.window.saved_paths.text())
        self.assertEqual(list(self.private.glob("Bank2Odoo_*")), [])
        text = self.window.status.text()
        self.window._thread_finished()  # orphaned/late callback, no active sender
        self.assertEqual(text, self.window.status.text())
        self.assertIsNone(self.window._thread)
        self.assertTrue(self.window.save_button.isEnabled())

    def test_error_summary_does_not_dump_source_fields(self):
        detail = "Invalid/ambiguous numeric format: 'customer-private-value'"
        self.assertNotIn("customer-private-value", human_error(detail))
        self.assertIn("مانده", human_error("Consecutive balance mismatch at source rows 5/6"))


if __name__ == "__main__":
    unittest.main()
