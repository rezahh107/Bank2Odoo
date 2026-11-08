"""Synthetic Concept A regression; not a physical Windows/accountant acceptance."""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout
from bank2odoo.ui.window import MainWindow
from tests.test_gui import statement


class ConceptADecisionDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.source = self.folder / "fictional_mellat.csv"
        self.private = self.folder / "private"
        self.private.mkdir()
        statement(self.source)
        self.w = MainWindow()
        self.w.show()
        self.app.processEvents()
        self.addCleanup(self.w.close)

    def _await(self, signal):
        if self.w._thread is None:
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        signal.connect(loop.quit)
        timer.start(15000)
        loop.exec()
        self.assertTrue(timer.isActive(), "Synthetic worker did not finish")
        timer.stop()
        self.assertIsNone(self.w._thread)

    def _detect(self):
        self.w.set_source(self.source)
        self._await(self.w.detection_done)
        self.assertIsNotNone(self.w.source)
        self.assertIsNotNone(self.w._selected_digest)

    def _approve(self):
        self.w.source_unit.setCurrentIndex(self.w.source_unit.findData("IRR"))
        self.w.target_unit.setCurrentIndex(self.w.target_unit.findData("IRR"))
        self.w.approved.setFocus()
        QTest.keyClick(self.w.approved, Qt.Key.Key_Space)
        self.assertTrue(self.w.approved.isChecked())
        self.assertEqual(self.w._approved_digest, self.w._selected_digest)

    def _convert(self):
        self._detect()
        self._approve()
        self.w.convert_button.click()
        self._await(self.w.conversion_done)
        self.assertIsNotNone(self.w.result)
        return self.w.result

    def test_initial_invalid_file_and_no_visual_authority(self):
        w = self.w
        self.assertEqual(w._decision_phase(), "initial")
        self.assertFalse(w.approved.isChecked())
        self.assertTrue(w.convert_button.styleSheet())
        self.assertEqual(w.select_button.styleSheet(), "")
        w.decision_heading.setText("PASS")
        w.result_state.setText("PASS")
        self.assertEqual(w._decision_phase(), "initial")
        w.save_files()
        self.assertIsNone(w._thread)
        self.assertFalse(w._saved)
        bad = self.folder / "fictional_invalid.csv"
        bad.write_bytes(b"invalid bank input")
        w.set_source(bad)
        self._await(w.detection_done)
        self.assertEqual(w._decision_phase(), "detect_error")
        self.assertIsNone(w.source)
        self.assertIsNone(w._selected_digest)
        self.assertFalse(w.approved.isChecked())
        with patch("bank2odoo.ui.window.QFileDialog.getOpenFileName",
                   return_value=("", "")) as picker:
            w.convert_button.click()
        picker.assert_called_once()
        self.assertEqual(w._decision_phase(), "detect_error")

    def test_financial_navigation_is_never_approval(self):
        w = self.w
        self._detect()
        self.assertEqual(w._decision_phase(), "financial_review")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        self.assertEqual(w._decision_phase(), "approval")
        w.convert_button.click()
        self.assertIs(self.app.focusWidget(), w.approved)
        self.assertFalse(w.approved.isChecked())
        self.assertIsNone(w._thread)
        self._approve()
        self.assertEqual(w._decision_phase(), "ready")
        self.assertIn("معتبر", w.context_status.text())
        w.target_unit.setCurrentIndex(w.target_unit.findData("TOMAN"))
        self.assertFalse(w.approved.isChecked())
        self.assertIsNone(w._approved_digest)
        self.assertFalse(w._conversion_is_ready_for_emphasis())
        w.factor.setText("11")
        w.approved.setChecked(True)
        self.assertFalse(w._conversion_is_ready_for_emphasis())
        w.convert_button.click()
        self.assertIsNone(w._thread)
        self.assertIsNone(w.result)
        self.assertIs(self.app.focusWidget(), w.factor)

    def test_real_pass_pair_and_next_picker_cancel(self):
        w = self.w
        result = self._convert()
        self.assertTrue(result.balance_status.startswith("PASS"))
        self.assertEqual(w._decision_phase(), "pass")
        self.assertTrue(w.candidate_state.isVisible())
        self.assertIn("تأیید حسابداری نیست", w.candidate_state.text())
        w.output_directory.setText(str(self.private))
        w.convert_button.click()
        self._await(w.save_done)
        self.assertTrue(w._saved)
        self.assertEqual(w._decision_phase(), "saved")
        self.assertIn("COMPLETE_PAIR", w.save_outcome_label.text())
        csv, report = Path(w.saved_csv_path.text()), Path(w.saved_report_path.text())
        self.assertNotEqual(csv, report)
        self.assertEqual(csv.read_text(encoding="utf-8-sig").splitlines()[0],
                         "Date,Label,Amount")
        self.assertTrue(report.is_file())
        original = (csv.read_bytes(), report.read_bytes())
        with patch("bank2odoo.ui.window.QFileDialog.getOpenFileName",
                   return_value=("", "")) as picker:
            w.convert_button.click()
        picker.assert_called_once()
        self.assertTrue(w._saved)
        self.assertEqual((csv.read_bytes(), report.read_bytes()), original)
        w.save_files()
        self.assertEqual((csv.read_bytes(), report.read_bytes()), original)

    def test_not_proven_and_safe_failed_save_reselection(self):
        statement(self.source, not_proven=True)
        w = self.w
        result = self._convert()
        self.assertFalse(result.balance_status.startswith("PASS"))
        self.assertEqual(w._decision_phase(), "not_proven")
        self.assertIn("NOT_PROVEN", w.result_state.text())
        self.assertTrue(w.save_box.isVisible())
        w.output_directory.setText(str(self.private))
        with patch("bank2odoo.ui.window.save_candidate",
                   side_effect=OSError("synthetic permission fault")):
            w.save_files()
            self._await(w.save_done)
        self.assertIs(w.result, result)
        self.assertEqual(w._decision_phase(), "save_error")
        self.assertFalse(w._saved)
        self.assertNotIn("COMPLETE_PAIR", w.save_outcome_label.text())
        self.assertFalse(w.saved_path_fields.isVisible())
        self.assertFalse(w.save_button.isEnabled())
        with patch("bank2odoo.ui.window.QFileDialog.getExistingDirectory",
                   return_value="") as picker:
            w.convert_button.click()
        picker.assert_called_once()
        self.assertEqual(w._decision_phase(), "save_error")
        with patch("bank2odoo.ui.window.QFileDialog.getExistingDirectory",
                   return_value=str(self.private)):
            w.convert_button.click()
        self.assertEqual(w._decision_phase(), "not_proven")
        self.assertTrue(w.save_button.isEnabled())

    def test_fixed_columns_focus_and_worker_presentation(self):
        w = self.w
        self.assertGreaterEqual(w.minimumWidth(), 900)
        for width, height in ((900, 650), (940, 650), (900, 480)):
            w.resize(width, height)
            self.app.processEvents()
            w._reflow_workspace()
            self.app.processEvents()
            self.assertEqual(w._workspace.direction(),
                             QBoxLayout.Direction.LeftToRight)
            self.assertGreater(w._input_column.geometry().center().x(),
                               w._result_column.geometry().center().x())
            self.assertEqual(w.scroll.horizontalScrollBar().maximum(), 0)
            for widget in (w.approved, w.convert_button, w.path_field):
                w.scroll.ensureWidgetVisible(widget)
                self.app.processEvents()
                pos = widget.mapTo(w.scroll.viewport(), widget.rect().center())
                self.assertTrue(w.scroll.viewport().rect().contains(pos))
        self._detect()
        for kind, expected in (("detect", "detecting"), ("convert", "converting"),
                               ("save", "saving")):
            w._job_state = {"kind": kind}
            w._set_busy(True)
            self.assertEqual(w._decision_phase(), expected)
            self.assertFalse(w.convert_button.isEnabled())
            w._job_state = None
            w._set_busy(False)
        self.assertFalse(w.approved.isChecked())
        self.assertEqual(w._decision_phase(), "financial_review")


if __name__ == "__main__":
    unittest.main()
