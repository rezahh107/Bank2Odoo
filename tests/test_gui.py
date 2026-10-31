"""Offscreen Qt interaction + real financial engine + paired-save regression.

Uses fictional statements only. This is not an accountant Windows acceptance test.
"""
import csv
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer, QThread, QPoint
from PySide6.QtTest import QTest
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication, QFormLayout, QGroupBox, QStyle, QStyleFactory, QBoxLayout

from bank2odoo.ui.window import MainWindow, _Job, human_error, preferred_style_key, latin
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

    def test_file_picker_copy_and_supported_formats(self):
        self.assertIn("انتخاب نشده", self.window.path_field.placeholderText())
        self.assertIn("انتخاب نشده", self.window.output_directory.placeholderText())
        with patch("bank2odoo.ui.window.QFileDialog.getOpenFileName",
                   return_value=("", "")) as picker:
            self.window._browse_source()
        format_filter = picker.call_args.args[3]
        self.assertIn("*.xls *.csv", format_filter)
        self.assertNotIn("*.xlsx", format_filter)
        self.assertIsNone(self.window.source)

    def test_factor_example_does_not_claim_accountant_approval(self):
        self.window.source_unit.setCurrentIndex(
            self.window.source_unit.findData("TOMAN")
        )
        self.window.target_unit.setCurrentIndex(
            self.window.target_unit.findData("IRR")
        )
        hint = self.window.factor_help.text()
        self.assertIn("10", hint)
        self.assertIn("نمونه محاسباتی", hint)
        self.assertIn("نه تأیید مالی", hint)
        self.assertFalse(self.window.approved.isChecked())

    def test_fluid_native_widget_layout_and_bidi_text(self):
        self.assertEqual(self.window.styleSheet(), "")
        self.assertEqual(self.window.approved.styleSheet(), "")
        self.assertEqual(self.window.source_unit.styleSheet(), "")
        self.assertEqual(len(self.window.findChildren(QGroupBox)), 4)
        self.assertEqual(self.window.approved.minimumHeight(), 52)
        self.assertGreaterEqual(
            self.window.approved.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth), 22
        )
        self.assertGreaterEqual(
            self.window.approved.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight), 22
        )
        self.assertFalse(self.window.approved.isChecked())
        self.assertEqual(self.window.approved.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        self.assertIn("تأیید", self.window.approved.accessibleName())
        self.assertEqual(self.window.path_field.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.assertEqual(self.window.factor.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.assertEqual([ord(char) for char in latin("123")], [0x2066, 49, 50, 51, 0x2069])
        self.assertLessEqual(self.window.journal.maximumWidth(), 480)
        self.assertLessEqual(self.window.source_unit.maximumWidth(), 390)
        forms = self.window.findChildren(QFormLayout)
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].rowWrapPolicy(), QFormLayout.RowWrapPolicy.WrapLongRows)
        for width, height in ((940, 830), (650, 520), (600, 480)):
            self.window.resize(width, height)
            self.app.processEvents()
            for widget in (self.window.approved, self.window.convert_button, self.window.directory_button):
                self.window.scroll.ensureWidgetVisible(widget)
                self.app.processEvents()
                viewport = self.window.scroll.viewport()
                target = widget.mapTo(viewport, widget.rect().center())
                self.assertTrue(viewport.rect().contains(target),
                                "Critical control should be scroll-reachable at this size")

    def test_confirmation_mouse_keyboard_disabled_and_revocation(self):
        self._select(self.source)
        self.window.source_unit.setCurrentIndex(self.window.source_unit.findData("IRR"))
        self.window.target_unit.setCurrentIndex(self.window.target_unit.findData("IRR"))
        self.window.journal.setText("ژورنال آزمایشی")
        self.assertFalse(self.window.approved.isChecked())
        self.window.scroll.ensureWidgetVisible(self.window.approved)
        self.app.processEvents()
        QTest.mouseClick(self.window.approved, Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.approved.isChecked())
        self.assertEqual(self.window._approved_digest, self.window._selected_digest)
        self.window.approved.setFocus()
        self.assertTrue(self.window.approved.hasFocus())
        QTest.keyClick(self.window.approved, Qt.Key.Key_Space)
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window._approved_digest)
        self.window.approved.setEnabled(False)
        QTest.mouseClick(self.window.approved, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.approved.isChecked())
        self.window.approved.setEnabled(True)
        QTest.keyClick(self.window.approved, Qt.Key.Key_Space)
        self.assertTrue(self.window.approved.isChecked())
        self.window.precision.setValue(2)
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window._approved_digest)

    def test_style_policy_prefers_fluent_only_if_available(self):
        styles = QStyleFactory.keys()
        self.assertTrue(styles, "Qt must expose at least one style")
        self.assertEqual(preferred_style_key(["Fusion", "windows11"], windows=True),
                         "windows11")
        self.assertEqual(preferred_style_key(["Fusion", "windows"], windows=True),
                         "Fusion")
        self.assertIsNone(preferred_style_key(["Fusion", "windows11"], windows=False))

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

    def test_conversion_guides_to_first_missing_input(self):
        self.window.start_conversion()
        self.assertIn("گزارش بانکی", self.window.status.text())
        self.assertIs(self.app.focusWidget(), self.window.select_button)

        self._select(self.source)
        self.window.start_conversion()
        self.assertIn("واحد پول فایل بانک", self.window.status.text())
        self.assertIs(self.app.focusWidget(), self.window.source_unit)

        self.window.source_unit.setCurrentIndex(self.window.source_unit.findData("IRR"))
        self.window.start_conversion()
        self.assertIn("واحد پول ژورنال مقصد", self.window.status.text())

        self.window.target_unit.setCurrentIndex(self.window.target_unit.findData("IRR"))
        self.window.start_conversion()
        self.assertIn("نام ژورنال", self.window.status.text())

        self.window.journal.setText("ژورنال آزمایشی")
        self.window.start_conversion()
        self.assertIn("تأیید صریح", self.window.status.text())
        self.assertIs(self.app.focusWidget(), self.window.approved)
        self.assertIsNone(self.window._thread)

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
        self.assertIn(latin(2) + " گردش", self.window.detected.text())
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
        self.assertIn("منطبق", self.window._metrics["balance"].text())
        self.assertIn("75", self.window._metrics["net"].text())
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
        from bank2odoo.cli import VERSION
        self.assertIn(f"Producing application version: Bank2Odoo {VERSION}\n", report)
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
        self.assertIn("احراز نشده", self.window._metrics["balance"].text())
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
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIn("انتخاب پوشه", self.window.convert_button.text())
        self.window.journal.setText("ژورنال تغییرکرده")
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())

    def test_repeated_worker_lifecycle_survives_failed_and_successful_saves(self):
        # Rapid successive real worker threads previously led to occasional
        # abrupt Windows Qt process termination without a unittest traceback.
        # Use fictional data only; run conversion and both save outcomes.
        for attempt in range(12):
            self._convert()
            directory = self.private / f"attempt_{attempt}"
            directory.mkdir()
            self.window.output_directory.setText(str(directory / "missing"))
            self._save()
            self.assertIn("خطای ذخیره", self.window.status.text())
            self.assertIsNone(self.window._thread)
            self.window.output_directory.setText(str(directory))
            self._save()
            self.assertIsNone(self.window._thread)
            self.assertEqual(len(list(directory.glob("Bank2Odoo_*"))), 2)

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

    def _await_join_attempts(self, calls: list[int], count: int) -> None:
        for _ in range(160):
            if len(calls) >= count:
                return
            QTest.qWait(10)
        self.fail(f"Expected {count} Qt join attempts, saw {calls}")

    def test_thread_join_immediate_success_and_single_publication(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        joins, outcomes = [], []
        original = self.window._wait_for_thread

        def joined(thread, timeout_ms):
            joins.append(timeout_ms)
            return original(thread, timeout_ms)

        self.window.save_done.connect(lambda: outcomes.append("save"))
        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self._save()
        self.assertEqual(joins, [5000])
        self.assertEqual(outcomes, ["save"])
        self.assertIsNone(self.window._thread)
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)

    def test_initial_failed_join_then_success_preserves_qt_object(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        calls, outcomes, deleted, worker_deleted = [], [], [], []
        original = self.window._wait_for_thread
        self.window.save_done.connect(lambda: outcomes.append("save"))

        def joined(thread, timeout_ms):
            calls.append(timeout_ms)
            if len(calls) == 1:
                self.assertTrue(isValid(thread))
                self.assertFalse(deleted)
                return False
            return original(thread, timeout_ms)

        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self.window.save_files()
            thread, worker = self.window._thread, self.window._worker
            thread.destroyed.connect(lambda: deleted.append(True))
            worker.destroyed.connect(lambda: worker_deleted.append(True))
            self._wait_operation(self.window.save_done)
        self.assertEqual(calls, [5000, 0])
        self.assertFalse(isValid(worker), "Worker deferred deletion did not finish")
        self.assertEqual(worker_deleted, [True])
        self.assertEqual(outcomes, ["save"])
        self.assertTrue(self.window._saved)
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)
        self._await_join_attempts(deleted, 1)

    def test_multiple_failed_joins_complete_conversion_once(self):
        self._select(self.source)
        self._approve()
        calls, outcomes = [], []
        original = self.window._wait_for_thread
        self.window.conversion_done.connect(lambda: outcomes.append("convert"))

        def joined(thread, timeout_ms):
            calls.append(timeout_ms)
            if len(calls) <= 3:
                self.assertTrue(isValid(thread))
                return False
            return original(thread, timeout_ms)

        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self.window.start_conversion()
            self._wait_conversion()
        self.assertEqual(calls, [5000, 0, 0, 0])
        self.assertEqual(outcomes, ["convert"])
        self.assertIsNotNone(self.window.result)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIn("انتخاب پوشه", self.window.convert_button.text())

    def test_persistent_failed_join_blocks_then_recovers_without_double_save(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        calls, outcomes, deleted = [], [], []
        allow_join = [False]
        original = self.window._wait_for_thread
        self.window.save_done.connect(lambda: outcomes.append("save"))

        def joined(thread, timeout_ms):
            calls.append(timeout_ms)
            return original(thread, timeout_ms) if allow_join[0] else False

        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self.window.save_files()
            thread = self.window._thread
            thread.destroyed.connect(lambda: deleted.append(True))
            try:
                self._await_join_attempts(calls, 3)
                self.assertEqual(calls[0], 5000)
                self.assertTrue(all(ms == 0 for ms in calls[1:]))
                self.assertTrue(isValid(thread), "QThread deleted before successful join")
                self.assertEqual(deleted, [])
                self.assertIs(self.window._thread, thread)
                self.assertFalse(self.window._saved)
                self.assertEqual(outcomes, [])
                self.assertFalse(self.window.save_button.isEnabled())
                self.assertIn("مسدود", self.window.status.text())
                self.window.save_files()
                self.window.start_conversion()
                self.assertIs(self.window._thread, thread)
                with patch("bank2odoo.ui.window.QMessageBox.information"):
                    self.assertFalse(self.window.close())
                self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)
            finally:
                allow_join[0] = True
                self._wait_operation(self.window.save_done)
        self.assertEqual(outcomes, ["save"])
        self.assertTrue(self.window._saved)
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)
        self._await_join_attempts(deleted, 1)

    def test_stale_retry_cannot_finish_new_worker_or_publish_again(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        outcomes = []
        self.window.save_done.connect(lambda: outcomes.append("save"))
        old_thread, old_state = None, None
        original = self.window._wait_for_thread
        calls = []

        def joined(thread, timeout_ms):
            calls.append(timeout_ms)
            return False if len(calls) == 1 else original(thread, timeout_ms)

        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self.window.save_files()
            old_thread, old_state = self.window._thread, self.window._job_state
            self._wait_operation(self.window.save_done)
        self.assertEqual(outcomes, ["save"])
        entered, released = Event(), Event()

        def delayed(path, raw):
            entered.set()
            if not released.wait(6):
                raise RuntimeError("synthetic detection timeout")
            return actual_read_statement(path, raw)

        other = self.private / "different_fictional.csv"
        statement(other)
        with patch("bank2odoo.ui.window.read_statement", side_effect=delayed):
            self.window.set_source(other)
            try:
                self.assertTrue(entered.wait(6))
                current_thread, current_state = self.window._thread, self.window._job_state
                with patch.object(self.window, "_wait_for_thread") as wait:
                    self.window._join_finished_thread(old_thread, old_state, 0)
                    self.window._thread_finished()  # no matching Qt signal sender
                    wait.assert_not_called()
                self.assertIs(self.window._thread, current_thread)
                self.assertIs(self.window._job_state, current_state)
                self.assertEqual(outcomes, ["save"])
            finally:
                released.set()
            self._wait_operation(self.window.detection_done)
        self.assertEqual(outcomes, ["save"])

    def test_failed_and_successful_paired_save_after_join_timeouts(self):
        self._convert()
        calls = []
        original = self.window._wait_for_thread

        def joined(thread, timeout_ms):
            calls.append(timeout_ms)
            return False if len(calls) % 2 == 1 else original(thread, timeout_ms)

        self.window.output_directory.setText(str(self.private / "missing"))
        with patch.object(self.window, "_wait_for_thread", side_effect=joined):
            self._save()
            self.assertEqual(calls, [5000, 0])
            self.assertIn("خطای ذخیره", self.window.status.text())
            self.assertFalse(self.window._saved)
            self.assertEqual(list(self.private.glob("Bank2Odoo_*")), [])
            self.window.output_directory.setText(str(self.private))
            self._save()
        self.assertEqual(calls, [5000, 0, 5000, 0])
        self.assertTrue(self.window._saved)
        self.assertIn("دو فایل ایجاد شدند", self.window.saved_paths.text())
        paths = list(self.private.glob("Bank2Odoo_*"))
        self.assertEqual(len(paths), 2)
        before = {path.name: path.read_bytes() for path in paths}
        self._save()  # An already-saved candidate must not overwrite the pair.
        self.assertEqual(before, {path.name: path.read_bytes() for path in paths})


    def test_workspace_responsive_columns_and_long_mixed_direction_paths(self):
        self.assertEqual(self.window.source_unit.accessibleName(), "واحد پول فایل بانک")
        self.assertEqual(self.window.target_unit.accessibleName(), "واحد پول ژورنال مقصد")
        very_long = "C:/Private/" + ("مسیر_ساختگی_" * 24) + "statement_2026_10_IRR_A" + "f" * 64 + ".csv"
        self.window.path_field.setText(very_long)
        self.window.output_directory.setText(very_long + "/output")
        for width, height, direction in (
            (940, 830, QBoxLayout.Direction.RightToLeft),
            (650, 520, QBoxLayout.Direction.TopToBottom),
            (600, 480, QBoxLayout.Direction.TopToBottom),
        ):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                self.app.processEvents()
                self.window._reflow_workspace()
                self.app.processEvents()
                self.assertEqual(self.window._workspace.direction(), direction,
                                 f"Measured breakpoint={self.window._workspace_breakpoint}, parts={self.window._workspace_measurements}, viewport={self.window.scroll.viewport().width()}")
                content = self.window.scroll.widget()
                for control in (
                    self.window.source_unit, self.window.target_unit,
                    self.window.journal, self.window.path_field,
                    self.window.approved, self.window.convert_button,
                    self.window.output_directory, self.window.directory_button,
                ):
                    x = control.mapTo(content, QPoint(0, 0)).x()
                    self.assertGreaterEqual(x, 0, control.objectName())
                    self.assertLessEqual(x + control.width(), content.width() + 1,
                                         f"Horizontal clipping: {control}, {width}px")
        self.assertEqual(self.window.path_field.text(), very_long)
        self.assertFalse(self.window.approved.isChecked())

    def test_primary_action_tracks_real_candidate_folder_and_saved_pair(self):
        self._convert()
        self.assertTrue(self.window.result_state.text().startswith("PASS"))
        self.assertIn("انتخاب پوشه", self.window.convert_button.text())
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertIs(self.app.focusWidget(), self.window.convert_button)
        with patch("bank2odoo.ui.window.QFileDialog.getExistingDirectory",
                   return_value=str(self.private)) as picker:
            self.window.convert_button.click()
        picker.assert_called_once()
        self.assertEqual(self.window.output_directory.text(), str(self.private))
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertEqual(self.window.convert_button.text(), "ذخیره CSV و گزارش کنترل")
        self.window.convert_button.click()
        self._wait_operation(self.window.save_done)
        self.assertTrue(self.window._saved)
        self.assertFalse(self.window.convert_button.isEnabled())
        self.assertEqual(len(list(self.private.glob("Bank2Odoo_*"))), 2)
        self.assertIn("Odoo", self.window.result_state.text())
        self.assertIn("control.txt", self.window.saved_paths.text())

    def test_financial_edit_and_approval_revocation_clear_stale_success(self):
        self._convert()
        self.window.output_directory.setText(str(self.private))
        self._save()
        self.assertIn("ذخیره هر دو فایل موفق بود", self.window.status.text())
        self.window.target_unit.setCurrentIndex(self.window.target_unit.findData("TOMAN"))
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.approved.isChecked())
        self.assertIsNone(self.window._approved_digest)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertNotIn("موفق بود", self.window.status.text())
        self.assertNotIn("دو فایل ایجاد شدند", self.window.saved_paths.text())
        self.assertIn("معتبر نیست", self.window.result_state.text())
        self.assertEqual(self.window.convert_button.text(), "اعتبارسنجی و تبدیل")
        self.window.start_conversion()
        self.assertIsNone(self.window._thread)
        self.assertIn("تأیید", self.window.status.text())

    def test_not_proven_never_claims_complete_balance_or_approved_import(self):
        statement(self.source, not_proven=True)
        self._convert()
        self.assertTrue(self.window.result_state.text().startswith("NOT_PROVEN"))
        self.assertNotIn("PASS", self.window.result_state.text())
        self.assertIn("احراز نشده", self.window._metrics["balance"].text())
        self.assertIn("پوشه", self.window.convert_button.text())
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertNotIn("تأیید حسابداری انجام شد", self.window.status.text())

    def test_error_summary_does_not_dump_source_fields(self):
        detail = "Invalid/ambiguous numeric format: 'customer-private-value'"
        self.assertNotIn("customer-private-value", human_error(detail))
        self.assertIn("مانده", human_error("Consecutive balance mismatch at source rows 5/6"))


if __name__ == "__main__":
    unittest.main()
