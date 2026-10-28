"""Isolated Windows-QPA checkbox paint matrix; not a production application change.

Run with QT_QPA_PLATFORM=windows on a GitHub-hosted Windows runner.
Results are diagnostic images, NOT physical-display or WCAG certification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from bank2odoo.ui.window import MainWindow
from tests.test_gui_palette import synthetic_palette


def full_palette(*, dark: bool, style_palette: QPalette) -> QPalette:
    """A deliberately coordinated test palette, not a Windows theme emulator."""
    p = QPalette(style_palette)
    sets = (
        {
            "Window": "#1b2029", "WindowText": "#f1f5f9",
            "Base": "#111722", "Text": "#f8fafc", "Mid": "#596678",
            "Button": "#293446", "ButtonText": "#f8fafc",
            "Light": "#69788e", "Midlight": "#435168", "Dark": "#0c111a",
            "Shadow": "#05070b", "Highlight": "#568bd0",
            "HighlightedText": "#ffffff", "PlaceholderText": "#a4b3c7",
            "AlternateBase": "#192231",
        }
        if dark else
        {
            "Window": "#f0f3f8", "WindowText": "#202a36",
            "Base": "#ffffff", "Text": "#17212e", "Mid": "#a5b2c3",
            "Button": "#e5ebf4", "ButtonText": "#17212e",
            "Light": "#ffffff", "Midlight": "#e4eaf1", "Dark": "#8494aa",
            "Shadow": "#526477", "Highlight": "#397ac8",
            "HighlightedText": "#ffffff", "PlaceholderText": "#69788a",
            "AlternateBase": "#f2f6fb",
        }
    )
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for name, hex_color in sets.items():
            p.setColor(group, getattr(QPalette.ColorRole, name), QColor(hex_color))
    return p


def palette_report(palette: QPalette) -> dict:
    roles = ("Window", "WindowText", "Base", "Text", "Mid",
             "Button", "ButtonText", "Light", "Dark", "Highlight")
    return {name: palette.color(getattr(QPalette.ColorRole, name)).name()
            for name in roles}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", required=True)
    args = parser.parse_args()
    output = Path(os.environ["RUNNER_TEMP"]) / "bank2odoo-visual" / "checkbox-matrix"
    output.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    available = QStyleFactory.keys()
    matching = next((key for key in available
                     if key.casefold() == args.style.casefold()), None)
    if matching is None:
        raise RuntimeError(f"Requested Qt style {args.style!r} unavailable: {available}")
    style = QStyleFactory.create(matching)
    assert style is not None
    app.setStyle(style)
    original_palette = QPalette(app.palette())
    records = []

    cases = [
        ("style-default", None),
        ("partial-light", synthetic_palette(dark=False)),
        ("complete-light", full_palette(dark=False, style_palette=original_palette)),
        ("partial-dark", synthetic_palette(dark=True)),
        ("complete-dark", full_palette(dark=True, style_palette=original_palette)),
    ]
    for palette_name, target_palette in cases:
        app.setPalette(QPalette(original_palette if target_palette is None else target_palette))
        app.processEvents()
        for use_proxy in (False, True):
            window = MainWindow()
            window.show()
            app.processEvents()
            if not use_proxy:
                # Only change this specific widget's painting style, not the app.
                # Production's _ApprovalIndicatorStyle remains unmodified.
                window.approved.setStyle(app.style())
                app.processEvents()
            window.scroll.ensureWidgetVisible(window.approved)
            app.processEvents()
            for state in ("unchecked", "checked", "focus", "disabled"):
                window.approved.setEnabled(True)
                window.approved.setChecked(state == "checked")
                if state == "focus":
                    window.approved.setFocus()
                else:
                    window.approved.clearFocus()
                if state == "disabled":
                    window.approved.setEnabled(False)
                app.processEvents()
                slug = f"{matching.lower()}-{palette_name}-{'proxy' if use_proxy else 'plain'}-{state}"
                crop = window.approval_panel.grab()
                screenshot = window.grab()
                panel_file = output / f"{slug}-panel.png"
                viewport_file = output / f"{slug}-window.png"
                if not crop.save(str(panel_file)) or not screenshot.save(str(viewport_file)):
                    raise RuntimeError(f"Screenshot capture failed: {slug}")
                records.append({
                    "name": slug, "requested_style": matching,
                    "effective_style": app.style().objectName(),
                    "widget_style": window.approved.style().objectName(),
                    "palette": palette_name, "proxy": use_proxy, "state": state,
                    "checked": window.approved.isChecked(),
                    "enabled": window.approved.isEnabled(),
                    "focused": window.approved.hasFocus(),
                    "indicator_width_metric": window.approved.style().pixelMetric(
                        window.approved.style().PixelMetric.PM_IndicatorWidth),
                    "indicator_height_metric": window.approved.style().pixelMetric(
                        window.approved.style().PixelMetric.PM_IndicatorHeight),
                    "panel_palette": palette_report(window.approval_panel.palette()),
                    "app_palette": palette_report(app.palette()),
                    "panel_screenshot": panel_file.name,
                    "window_screenshot": viewport_file.name,
                    "device_pixel_ratio": crop.devicePixelRatio(),
                    "window_px": [screenshot.width(), screenshot.height()],
                })
                print("QPA_CASE", json.dumps(records[-1], ensure_ascii=False))
            window.close()
            window.deleteLater()
            app.processEvents()

    report = {
        "limits": [
            "GitHub-hosted Windows native QPA; not accountant's physical display",
            "Synthetic dark/light palettes are not Windows OS personalization themes",
            "QT_SCALE_FACTOR is not a substitute for physical 100/125/150 percent DPI",
            "Results must be interpreted with pixel rendering and native-style limits",
            "No financial engine, Odoo, bank data or production code was changed",
        ],
        "available_styles": available, "style": matching,
        "os": os.name, "qpa": os.environ.get("QT_QPA_PLATFORM"),
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"),
        "cases": records,
    }
    (output / f"{matching.lower()}-matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MATRIX_COMPLETE style={matching} cases={len(records)} dir={output}")
    app.setPalette(original_palette)


if __name__ == "__main__":
    main()
