"""Synthetic Qt palette contract: dark and light are not financial-data tests.

These checks validate the actual widget palettes / local presentation rules.
Windows-QPA captures are separate evidence for pixel rendering.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QGroupBox, QLabel

from bank2odoo.ui.window import MainWindow


def synthetic_palette(*, dark: bool) -> QPalette:
    """Make text and surface differences strong enough to expose fixed light skins."""
    p = QPalette()
    colors = (
        ("#1b2029", "#f1f5f9", "#111722", "#f8fafc", "#596678")
        if dark else
        ("#f0f3f8", "#202a36", "#ffffff", "#17212e", "#a5b2c3")
    )
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, value in zip((
                QPalette.ColorRole.Window, QPalette.ColorRole.WindowText,
                QPalette.ColorRole.Base, QPalette.ColorRole.Text,
                QPalette.ColorRole.Mid), colors):
            p.setColor(group, role, QColor(value))
    return p


def contrast_ratio(foreground: QColor, background: QColor) -> float:
    """WCAG-style relative-luminance contrast for opaque solid palette colors."""
    def luminance(color: QColor) -> float:
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class PaletteContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = QPalette(self.app.palette())

    def tearDown(self):
        self.app.setPalette(self.original)
        self.app.processEvents()

    def _check_palette(self, *, dark: bool) -> None:
        palette = synthetic_palette(dark=dark)
        self.app.setPalette(palette)
        window = MainWindow()
        window.show()
        self.app.processEvents()
        try:
            notice_text = next(label for label in window.findChildren(QLabel)
                               if label.text().startswith("فقط تهیه نامزد"))
            notice = notice_text.parentWidget()
            approved: QCheckBox = window.approved
            approval = approved.parentWidget()
            approval_hint = next(label for label in approval.findChildren(QLabel)
                                 if "ژورنال" in label.text())
            for name, panel, texts in (
                    ("notice", notice, [notice_text]),
                    ("financial approval", approval, [approved, approval_hint])):
                with self.subTest(surface=name, dark=dark):
                    self.assertIsInstance(panel, QFrame)
                    expected_bg = palette.color(QPalette.ColorRole.Window)
                    expected_fg = palette.color(QPalette.ColorRole.WindowText)
                    self.assertEqual(panel.palette().color(QPalette.ColorRole.Window),
                                     expected_bg, "panel must not use a fixed light background")
                    for label in texts:
                        foreground = label.palette().color(QPalette.ColorRole.WindowText)
                        self.assertEqual(foreground, expected_fg)
                        self.assertGreaterEqual(contrast_ratio(foreground, expected_bg), 4.5)

            cards = window.findChildren(QGroupBox)
            self.assertEqual(len(cards), 4)
            expected_bg = palette.color(QPalette.ColorRole.Base)
            expected_fg = palette.color(QPalette.ColorRole.Text)
            for card in cards:
                with self.subTest(card=card.title(), dark=dark):
                    # QSS participates in actual Qt painting and can override QPalette.
                    # Verify both the local QSS paint colors and the widget/child palettes.
                    rules = card.styleSheet().lower()
                    self.assertIn("background: " + expected_bg.name(), rules)
                    self.assertIn("color: " + expected_fg.name(), rules)
                    self.assertEqual(card.palette().color(QPalette.ColorRole.Window), expected_bg)
                    for label in card.findChildren(QLabel):
                        if label.parentWidget() is not card:
                            continue  # Nested approval panel has its own surface.
                        foreground = label.palette().color(QPalette.ColorRole.WindowText)
                        self.assertGreaterEqual(contrast_ratio(foreground, expected_bg), 4.5)
                    self.assertGreaterEqual(contrast_ratio(expected_fg, expected_bg), 4.5)
            self.assertFalse(approved.isChecked())
            self.assertEqual(approved.minimumHeight(), 52)
            self.assertFalse(window.styleSheet(), "native control rendering stays active")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_palette_change_rethemes_existing_window(self):
        """An already open window follows Qt when the application palette changes."""
        self.app.setPalette(synthetic_palette(dark=False))
        window = MainWindow()
        window.show()
        self.app.processEvents()
        try:
            self.app.setPalette(synthetic_palette(dark=True))
            for _ in range(5):
                self.app.processEvents()  # deliver deferred changeEvent updates
            dark = self.app.palette()
            card = window.findChildren(QGroupBox)[0]
            self.assertEqual(card.palette().color(QPalette.ColorRole.Window),
                             dark.color(QPalette.ColorRole.Base))
            self.assertIn(dark.color(QPalette.ColorRole.Text).name(),
                          card.styleSheet().lower())
            self.assertEqual(window.approved.parentWidget().palette().color(
                QPalette.ColorRole.Window), dark.color(QPalette.ColorRole.Window))
            self.assertEqual(window.status.palette().color(QPalette.ColorRole.WindowText),
                             dark.color(QPalette.ColorRole.Text))
            self.assertFalse(window.approved.isChecked())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_light_palette_surfaces(self):
        self._check_palette(dark=False)

    def test_dark_palette_surfaces(self):
        self._check_palette(dark=True)


if __name__ == "__main__":
    unittest.main()
