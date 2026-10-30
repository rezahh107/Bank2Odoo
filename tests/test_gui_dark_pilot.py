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

    @staticmethod
    def _native_color_roles(palette):
        """Read effective Qt colors, including Windows disabled color groups."""
        roles = (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                 QPalette.ColorRole.Text, QPalette.ColorRole.Button,
                 QPalette.ColorRole.Highlight)
        groups = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Disabled,
                  QPalette.ColorGroup.Inactive)
        return {
            (group, role): palette.color(group, role).name()
            for group in groups for role in roles
        }

    def test_dark_exit_restores_actual_native_windows11_colors(self):
        """Red on reviewed PR Head: native #efefef becomes standard #d4d0c8."""
        available = {key.casefold(): key for key in QStyleFactory.keys()}
        if "windows11" not in available:
            self.skipTest("Windows11 Qt QStyle unavailable")
        with patch("bank2odoo.ui.window.sys.platform", "win32"):
            style = QStyleFactory.create(available["windows11"])
            self.assertIsNotNone(style)
            self.app.setStyle(style)
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
            expected = self._native_color_roles(self.app.palette())
            expected_style = self.app.style().objectName().casefold()
            # This checks the premise without assuming a fixed OS light color.
            standard = self._native_color_roles(self.app.style().standardPalette())
            self.assertNotEqual(
                expected, standard,
                "Native and QStyle.standardPalette() must differ for this "
                "Windows regression fixture; otherwise the negative control "
                "cannot falsify the original defect",
            )
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Dark)
            self.assertEqual(self.pilot.dark, True)
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
            self.assertEqual(self.app.style().objectName().casefold(), expected_style)
            self.assertEqual(
                self._native_color_roles(self.app.palette()), expected,
                "Dark exit must recover actual platform-managed colors; "
                "QStyle.standardPalette is not the native platform palette",
            )

    def test_dark_to_unknown_restores_native_roles_and_nonrecursive_updates(self):
        available = {key.casefold(): key for key in QStyleFactory.keys()}
        if "windows11" not in available:
            self.skipTest("Windows11 Qt QStyle unavailable")
        with patch("bank2odoo.ui.window.sys.platform", "win32"):
            self.app.setStyle(QStyleFactory.create(available["windows11"]))
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
            expected = self._native_color_roles(self.app.palette())
            window = self._window()
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Dark)
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Unknown)
            for _ in range(8):
                self.app.processEvents()
            self.assertEqual(self._native_color_roles(self.app.palette()), expected)
            self.assertFalse(self.pilot.dark)
            self.assertFalse(self.pilot._applying)
            self.assertFalse(self.pilot._queued)
            self.assertFalse(window._presentation_refresh_queued)
            self.assertEqual(window.approved.styleSheet(), "")
            self.assertEqual(window.convert_button.styleSheet(), "")
            self.assertEqual(self._metric(window.approved), (22, 22, 22, 22))

    def test_fusion_fallback_resets_native_colors_when_style_name_does_not_change(self):
        """Dark->Light with Fusion both sides must still reset via QApplication.setStyle."""
        if not any(k.casefold() == "fusion" for k in QStyleFactory.keys()):
            self.skipTest("Fusion Qt style unavailable")
        with patch("bank2odoo.ui.window.sys.platform", "win32"), patch(
            "bank2odoo.ui.window.QStyleFactory.keys", return_value=["Fusion"]
        ):
            self.app.setStyle(QStyleFactory.create("Fusion"))
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
            expected = self._native_color_roles(self.app.palette())
            self.pilot.apply(_test_scheme=Qt.ColorScheme.Dark)
            with patch(
                "bank2odoo.ui.window.QStyleFactory.create",
                wraps=QStyleFactory.create,
            ) as create_style:
                self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
                self.assertTrue(
                    create_style.called,
                    "Fusion fallback must reapply its Qt style to release "
                    "the explicit dark palette even if the style name is unchanged",
                )
            self.assertEqual(self.app.style().objectName().casefold(), "fusion")
            self.assertEqual(self._native_color_roles(self.app.palette()), expected)

    def test_native_restore_failure_is_explicit_and_recoverable(self):
        """Do not silently claim a restored palette if Qt cannot create its style."""
        available = {name.casefold(): name for name in QStyleFactory.keys()}
        if "fusion" not in available:
            self.skipTest("Fusion Qt QStyle unavailable")
        w = self._window()
        self._scheme(Qt.ColorScheme.Dark)
        with patch("bank2odoo.ui.window.sys.platform", "win32"), patch(
            "bank2odoo.ui.window.QStyleFactory.create", return_value=None
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Cannot restore the native Qt palette"
            ):
                self.pilot.apply(_test_scheme=Qt.ColorScheme.Light)
        self.assertTrue(self.pilot.dark)
        self.assertTrue(self.pilot._applied)
        self.assertFalse(self.pilot._applying)
        self._scheme(Qt.ColorScheme.Light)
        self.assertFalse(self.pilot.dark)
        self.assertEqual(w.approved.styleSheet(), "")

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
        w.source_unit.showPopup()
        self.app.processEvents()
        self.assertTrue(w.source_unit.view().isVisible(),
                        "Native ComboBox popup must remain available in Fusion Dark")
        w.source_unit.hidePopup()
        self.app.processEvents()
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

    def test_app_local_qstylehints_signal_rethemes_without_refresh_loop(self):
        """Exercise Qt 6.11 colorSchemeChanged asynchronously, not only the test seam."""
        w = self._window()
        hints = self.app.styleHints()
        initial = hints.colorScheme()
        try:
            hints.setColorScheme(Qt.ColorScheme.Dark)
            for _ in range(8):
                self.app.processEvents()
            if hints.colorScheme() != Qt.ColorScheme.Dark:
                self.skipTest("This Qt backend cannot honor test-only colorScheme override")
            if "Fusion" not in QStyleFactory.keys():
                self.skipTest("Fusion unavailable")
            self.assertTrue(self.pilot.dark)
            self.assertEqual(self.app.style().objectName().casefold(), "fusion")
            self.assertFalse(w._presentation_refresh_queued)
            # Switching back through the signal must remove all local dark QSS.
            hints.setColorScheme(Qt.ColorScheme.Light)
            for _ in range(8):
                self.app.processEvents()
            self.assertFalse(self.pilot.dark)
            self.assertEqual(w.approved.styleSheet(), "")
            self.assertEqual(w.convert_button.styleSheet(), "")
            self.assertFalse(w._presentation_refresh_queued)
            self.assertFalse(self.pilot._queued)
        finally:
            hints.setColorScheme(initial)
            for _ in range(8):
                self.app.processEvents()

    def test_presentation_switch_during_synthetic_busy_keeps_controls_locked(self):
        """Simulated UI-only busy, not a physical worker cancellation test."""
        w = self._window()
        self._validated_approval(w)
        digest = w._approved_digest
        w._set_busy(True)
        self.assertFalse(w.approved.isEnabled())
        self.assertFalse(w.convert_button.isEnabled())
        for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            self._scheme(scheme)
            self.assertFalse(w.approved.isEnabled())
            self.assertFalse(w.convert_button.isEnabled())
            self.assertEqual(w._approved_digest, digest)
            self.assertTrue(w.approved.isChecked())
        w._set_busy(False)
        self.assertTrue(w.approved.isEnabled())
        self.assertEqual(w._approved_digest, digest)

    def test_poor_unchecked_indicator_pixel_negative_control(self):
        """Actual pixel contrast, not merely QPalette roles or string colors."""
        w = self._window()
        self._scheme(Qt.ColorScheme.Dark)
        cb = w.approved

        def painted_contrast_fraction():
            opts = QStyleOptionButton()
            opts.initFrom(cb)
            rect = cb.style().subElementRect(
                QStyle.SubElement.SE_CheckBoxIndicator, opts, cb
            )
            image = cb.grab().toImage()
            x0, y0 = rect.x(), rect.y()
            bg = image.pixelColor(max(0, x0-5), y0 + rect.height()//2)

            def lum(color):
                srgb = [color.redF(), color.greenF(), color.blueF()]
                linear = [c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
                          for c in srgb]
                return .2126*linear[0]+.7152*linear[1]+.0722*linear[2]

            ref = lum(bg)
            values = []
            for y in range(y0, y0 + rect.height()):
                for x in range(x0, x0 + rect.width()):
                    v = lum(image.pixelColor(x,y))
                    contrast = (max(v,ref)+.05)/(min(v,ref)+.05)
                    values.append(contrast)
            return sum(v >= 3 for v in values)/len(values)

        # The known deliberately inadequate fixture is fully local to the
        # production checkbox and uses the exact same 22px proxy.
        cb.setStyleSheet(
            "QCheckBox#financialApproval::indicator:unchecked {"
            " border: 1px solid #161B22; background-color: #151A21; }"
        )
        self.app.processEvents()
        poor_fraction = painted_contrast_fraction()
        self.assertEqual(self._metric(cb), (22,22,22,22))
        cb.setStyleSheet(_APPROVAL_DARK_QSS)
        self.app.processEvents()
        fixed_fraction = painted_contrast_fraction()
        self.assertEqual(self._metric(cb), (22,22,22,22))
        self.assertLess(poor_fraction, .05,
                        "Negative weak indicator must not render as adequate")
        self.assertGreaterEqual(fixed_fraction, .05,
                                "Local border must visibly repair the indicator")
        self.assertFalse(cb.isChecked())

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
