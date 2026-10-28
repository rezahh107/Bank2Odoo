"""Capture native Qt colorScheme hints on hosted Windows QPA, without synthetic QPalette.

Qt colorScheme hints are not physical Windows personalization or DPI acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory
from bank2odoo.ui.window import MainWindow, configure_application


def palette_roles(p: QPalette) -> dict:
    return {n: p.color(getattr(QPalette.ColorRole, n)).name()
            for n in ("Window", "WindowText", "Base", "Text", "Button", "ButtonText")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["windows11", "Fusion"], required=True)
    parser.add_argument("--scheme", choices=["Light", "Dark", "Unknown"], required=True)
    args = parser.parse_args()

    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    configure_application(app)  # Exact product startup configuration.
    if args.style.lower() != "windows11":
        alternative = QStyleFactory.create(args.style)
        assert alternative is not None
        app.setStyle(alternative)

    initial = palette_roles(app.palette())
    initial_scheme = app.styleHints().colorScheme().name
    app.styleHints().setColorScheme(getattr(Qt.ColorScheme, args.scheme))
    for _ in range(12):
        app.processEvents()

    output = Path(os.environ["RUNNER_TEMP"]) / "bank2odoo-visual" / "native-scheme"
    output.mkdir(parents=True, exist_ok=True)
    window = MainWindow()
    window.show()
    window.scroll.ensureWidgetVisible(window.approved)
    for _ in range(6):
        app.processEvents()
    observations = []
    for checked in (False, True):
        window.approved.blockSignals(True)
        window.approved.setChecked(checked)
        window.approved.blockSignals(False)
        for _ in range(5):
            app.processEvents()
        name = f"{args.style.lower()}-{args.scheme.lower()}-{'checked' if checked else 'unchecked'}"
        panel = window.approval_panel.grab()
        if not panel.save(str(output / (name + ".png"))):
            raise RuntimeError("Failed to capture " + name)
        observations.append({
            "name": name, "checked": window.approved.isChecked(),
            "checkbox_style_class": window.approved.style().metaObject().className(),
            "panel_palette": palette_roles(window.approval_panel.palette()),
            "screenshot": name + ".png",
        })
    report = {
        "style": app.style().objectName(),
        "selected_style": args.style,
        "requested_color_scheme": args.scheme,
        "initial_scheme": initial_scheme,
        "effective_scheme": app.styleHints().colorScheme().name,
        "initial_palette": initial,
        "current_app_palette": palette_roles(app.palette()),
        "qpa": os.getenv("QT_QPA_PLATFORM"),
        "limitations": [
            "Hosted Windows QPA, not an actual user's Windows desktop",
            "Qt color scheme hint may be ignored or partially supported",
            "No actual Windows personalization, physical DPI, or font rendering proof",
            "Checked state is paint-only; production approval rules remain unchanged",
        ],
        "observations": observations,
    }
    (output / f"{args.style.lower()}-{args.scheme.lower()}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NATIVE_SCHEME_RESULT", json.dumps(report, ensure_ascii=False))
    window.close()


if __name__ == "__main__":
    main()
