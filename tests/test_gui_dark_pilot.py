"""Bounded dark-theme pilot, synthetic OS hint and approval safety regressions.

These are offscreen Qt checks, not physical Windows11 appearance acceptance.
"""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QComboBox, QGroupBox, QLineEdit,
                               QSpinBox, QStyle, QStyleFactory, QStyleOptionButton)

from bank2odoo.ui.window import (MainWindow, _APPROVAL_DARK_QSS,
    _PRIMARY_DARK_QSS, configure_application)


class DarkThemePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_palette = QPalette(self.app.palette())
        self.original_style = self.app.style().objectName()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.windows = []
        self.addCleanup(self._close_windows)
        # Windows offscreen Qt can expose a different QStyleFactory set.
        # Simulate OS *scheme* explicitly but use real Qt painting/style APIs.
        with patch("bank2odoo.ui.window.sys.platform", "win32"):
            configure_application(self.app)
            self.pilot = self.app._bank2odoo_appearance_pilot
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)

    def _close_windows(self):
        for w in self.windows:
            w.close()
            w.deleteLater()
        self.app.processEvents()
        with patch("bank2odoo.ui.window.sys.platform", "win32"):
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
        style = QStyleFactory.create(self.original_style)
        if style:
            self.app.setStyle(style)
        self.app.setPalette(self.original_palette)
        self.app.processEvents()

    def _window(self):
        w = MainWindow()
        self.windows.append(w)
        w.show()
        self.app.processEvents()
        return w

    def _scheme(self, scheme):
        with patch("bank2odoo.ui.window.sys.platform", "win32"):
            self.pilot.apply(_test_scheme=scheme)
        for _ in range(5):
            self.app.processEvents()

    def _metric(self, checkbox):
        opt = QStyleOptionButton()
        opt.initFrom(checkbox)
        width = checkbox.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, opt, checkbox)
        height = checkbox.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, opt, checkbox)
        rect = checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,
                                               opt, checkbox)
        return width, height, rect.width(), rect.height()

    def _fixture(self, path):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Fictional test data — not a bank statement"])
            writer.writerow(["ردیف", "تاریخ", "زمان", "شماره سریال", "شرح",
                             "مبلغ گردش بدهکار", "مبلغ گردش بستانکار",
                             "مانده", "واریز کننده/ذینفع"])
            writer.writerow(["1", "1405/07/01", "10:00", "A1",
                             "واریز آزمایشی", "0", "100", "100"])
            writer.writerow(["2", "1405/07/02", "11:00", "A2",
                             "کارمزد آزمایشی", "25", "0", "75"])

    def _wait_detect(self, w):
        if w._thread is None:
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        w.detection_done.connect(loop.quit)
        timer.start(15000)
        loop.exec()
        self.assertTrue(timer.isActive(), "Synthetic detection timed out")
        self.assertIsNone(w._thread)

    def _validated_approval(self, w):
        path = Path(self.temp.name) / "fictional.csv"
        self._fixture(path)
        w.set_source(path)
        self._wait_detect(w)
        self.assertIsNotNone(w._selected_digest)
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.journal.setText("ژورنال آزمایشی")
        w.approved.setChecked(True)
        self.assertTrue(w.approved.isChecked())
        self.assertEqual(w._approved_digest, w._selected_digest)

    def test_native_light_selection_and_scoped_dark_rules(self):
        w = self._window()
        self.assertEqual(w.approved.styleSheet(), "")
        self.assertEqual(w.convert_button.styleSheet(), "")
        self.assertFalse(w.styleSheet())
        self._scheme(Qt.ColorScheme.Dark)
        if "Fusion" not in QStyleFactory.keys():
            self.skipTest("Fusion not installed; no dark override may be fabricated")
        self.assertEqual(self.app.style().objectName().casefold(), "fusion")
        self.assertEqual(w.approved.styleSheet(), _APPROVAL_DARK_QSS)
        self.assertEqual(w.convert_button.styleSheet(), _PRIMARY_DARK_QSS)
        self.assertFalse(w.styleSheet())
        self.assertFalse(w.source_unit.styleSheet())
        self.assertFalse(w.journal.styleSheet())
        self.assertFalse(w.precision.styleSheet())
        self.assertEqual(len(w.findChildren(QGroupBox)), 4)
        for control in (w.source_unit, w.target_unit, w.journal, w.factor,
                        w.precision, w.approved, w.convert_button):
            self.assertTrue(control.isEnabled() or control is w.factor)
        for value in self._metric(w.approved):
            self.assertGreaterEqual(value, 22)
        self.assertEqual(w.approved.accessibleName(), "تأیید صریح اطلاعات مالی")
        self._scheme(Qt.ColorScheme.Light)
        self.assertEqual(w.approved.styleSheet(), "")
        self.assertEqual(w.convert_button.styleSheet(), "")
        self.assertEqual(self.pilot.dark, False)

    def test_dark_palette_roles_native_inputs_and_focus(self):
        w = self._window()
        self._scheme(Qt.ColorScheme.Dark)
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window), QColor("#151A21"))
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Text), QColor("#EAF1F7"))
        for control in (w.source_unit, w.target_unit, w.precision, w.factor, w.journal):
            self.assertEqual(control.styleSheet(), "")
        w.source_unit.setFocus()
        QTest.keyClick(w.source_unit, Qt.Key.Key_Down)
        self.assertIsNotNone(w.source_unit.currentData())
        w.journal.setFocus()
        QTest.keyClicks(w.journal, "test")
        self.assertEqual(w.journal.text(), "test")
        w.precision.setFocus()
        QTest.keyClick(w.precision, Qt.Key.Key_Up)
        self.assertEqual(w.precision.value(), 1)
        self.assertEqual(w.factor.layoutDirection(), Qt.LayoutDirection.LeftToRight)

    def test_tab_space_full_row_and_disabled_indicator_metric(self):
        w = self._window()
        self._scheme(Qt.ColorScheme.Dark)
        self.assertFalse(w.approved.isChecked())
        self.assertEqual(w.approved.minimumHeight(), 52)
        w.approved.setFocus()
        QTest.keyClick(w.approved, Qt.Key.Key_Space)
        self.assertFalse(w.approved.isChecked(), "No source must never create approval")
        self._validated_approval(w)
        w.approved.setFocus()
        QTest.keyClick(w.approved, Qt.Key.Key_Space)
        self.assertFalse(w.approved.isChecked())
        QTest.mouseClick(w.approved, Qt.MouseButton.LeftButton,
                         pos=QPoint(5, w.approved.height() // 2))
        self.assertTrue(w.approved.isChecked())
        w.approved.setEnabled(False)
        self.assertFalse(w.approved.isEnabled())
        self.assertEqual(w.approved.accessibleName(), "تأیید صریح اطلاعات مالی")
        for metric in self._metric(w.approved):
            self.assertGreaterEqual(metric, 22)

    def test_theme_switch_never_revokes_or_bypasses_valid_financial_approval(self):
        w = self._window()
        self._validated_approval(w)
        original = (w.approved.isChecked(), w._approved_digest,
                    w._selected_digest, w.result, w.save_button.isEnabled())
        for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light,
                       Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            self._scheme(scheme)
            current = (w.approved.isChecked(), w._approved_digest,
                       w._selected_digest, w.result, w.save_button.isEnabled())
            self.assertEqual(current, original, "Pure theme switch modified financial state")
        w.journal.setText("تغییر واقعی در ژورنال")
        self.assertFalse(w.approved.isChecked(), "Real context editing must revoke approval")
        self.assertIsNone(w._approved_digest)
        self.assertIsNone(w.result)
        self.assertFalse(w.save_button.isEnabled())

    def test_manual_palette_change_rethemes_panels_without_reapproval(self):
        w = self._window()
        self._validated_approval(w)
        original_digest = w._approved_digest
        palette = QPalette(self.app.palette())
        palette.setColor(QPalette.ColorRole.Base, QColor("#233344"))
        self.app.setPalette(palette)
        for _ in range(7):
            self.app.processEvents()
        card = w.findChildren(QGroupBox)[0]
        self.assertIn("#233344", card.styleSheet().lower())
        self.assertTrue(w.approved.isChecked())
        self.assertEqual(original_digest, w._approved_digest)
        self.assertFalse(w._presentation_refresh_queued)


if __name__ == "__main__":
    unittest.main()
