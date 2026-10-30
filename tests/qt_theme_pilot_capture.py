"""Capture synthetic full-product BEFORE/AFTER Qt theme pilot states.

Only fictional bank fixtures in TemporaryDirectory. Windows hosted QPA !=
interactive Windows11 OS desktop. Explicit QStyleHints override is a SIMULATION.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer, qVersion
from PySide6.QtGui import QFontInfo, QPalette
from PySide6.QtWidgets import QApplication

from bank2odoo.ui import window as current_ui

BASE_SHA = "d06b35f41ac46936716b186fb1dfac33da983eb9"
STATES = ("initial", "validation_error", "approval_unchecked",
          "approval_checked", "keyboard_focus", "conversion_busy",
          "not_proven_result", "ready_to_save")
SIZES = ((940, 830), (650, 520))


def fixture(file: Path) -> None:
    with file.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Fictional test data — not a bank statement"])
        w.writerow(["ردیف", "تاریخ", "زمان", "شماره سریال", "شرح",
                    "مبلغ گردش بدهکار", "مبلغ گردش بستانکار",
                    "مانده", "واریز کننده/ذینفع"])
        w.writerow(["1", "1405/07/01", "10:00", "A1",
                    "واریز آزمایشی", "0", "100", "100"])
        # Deliberately lacks ending balance: conversion should remain
        # NOT_PROVEN while still producing an explicitly review-only candidate.
        w.writerow(["2", "1405/07/02", "11:00", "A2",
                    "کارمزد آزمایشی", "25", "0", ""])


def wait_finished(w, signal, app) -> None:
    if w._thread is None:
        return
    event = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(event.quit)
    signal.connect(event.quit)
    timer.start(20000)
    event.exec()
    if not timer.isActive():
        raise RuntimeError("Synthetic worker timed out")
    for _ in range(100):
        app.processEvents()
        if w._thread is None:
            break
    if w._thread is not None:
        raise RuntimeError("Qt worker not joined after synthetic result")


def load_before(directory: Path):
    raw = subprocess.check_output(["git", "show",
                                   BASE_SHA + ":bank2odoo/ui/window.py"])
    file = directory / "bank2odoo_before.py"
    file.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("bank2odoo_before", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(app, w, out: Path, label: str, records: list[dict]):
    w.scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    # A product UI at 650x520 scrolls; preserve both positions without
    # replacing real widget geometry or drawing a reconstructed picture.
    for view in ("top", "bottom"):
        if view == "bottom":
            w.scroll.verticalScrollBar().setValue(
                w.scroll.verticalScrollBar().maximum())
            app.processEvents()
        name = f"{label}_{view}.png"
        pm = w.grab()
        if pm.isNull() or not pm.save(str(out / name), "PNG"):
            raise RuntimeError("Cannot save native-resolution " + name)
        records.append({
            "file": name, "width": pm.width(), "height": pm.height(),
            "device_pixel_ratio": pm.devicePixelRatio(),
            "approved": w.approved.isChecked(),
            "selected_digest_present": w._selected_digest is not None,
            "approval_digest_matches": (
                w._approved_digest is not None and
                w._approved_digest == w._selected_digest
            ),
            "busy": w.busy.isVisible(), "save_enabled": w.save_button.isEnabled(),
            "result_present": w.result is not None,
            "result_balance_status": (
                w.result.balance_status if w.result else None
            ),
        })


def take(app, module, phase: str, scheme: str, width: int, height: int,
         root: Path, synthetic: Path, records: list[dict]):
    app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light
    )
    app.processEvents()
    module.configure_application(app)
    # No actual OS scheme is inferred. A Qt test-set hint is app-specific.
    w = module.MainWindow()
    w.resize(width, height)
    w.show()
    app.processEvents()
    label = f"{phase}_{scheme}_{width}x{height}"
    case = {
        "phase": phase, "requested_test_scheme": scheme,
        "qt_effective_color_scheme": app.styleHints().colorScheme().name,
        "effective_style": app.style().objectName(),
        "resolved_font": QFontInfo(w.approved.font()).family(),
        "effective_app_palette": {
            k: app.palette().color(getattr(QPalette.ColorRole, k)).name()
            for k in ("Window", "WindowText", "Base", "Text", "Button",
                      "ButtonText", "Highlight", "HighlightedText")
        },
        "checkbox_style_qss": w.approved.styleSheet(),
        "primary_style_qss": w.convert_button.styleSheet(),
        "font_glyph_fallback_verified": False,
        "capture_records": [],
    }
    try:
        def grab(state):
            snapshot(app, w, root, label + "_" + state,
                     case["capture_records"])

        grab("initial")
        w.start_conversion()
        if "تبدیل آغاز نشد" not in w.status.text():
            raise AssertionError("Expected synthetic validation failure state")
        grab("validation_error")
        w.set_source(synthetic)
        wait_finished(w, w.detection_done, app)
        if w.source is None:
            raise AssertionError("Synthetic source failed detection")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.journal.setText("ژورنال ساختگی")
        grab("approval_unchecked")
        w.approved.setChecked(True)
        if not w.approved.isChecked() or w._approved_digest != w._selected_digest:
            raise AssertionError("Synthetic approval failed before theme capture")
        grab("approval_checked")
        w.approved.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        grab("keyboard_focus")
        w.start_conversion()
        if w._thread is None:
            raise AssertionError("Expected conversion worker to start")
        # Observe the authentic busy state before awaiting the result.
        grab("conversion_busy")
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Expected synthetic NOT_PROVEN result")
        grab("not_proven_result")
        w.output_directory.setText(str(synthetic.parent))
        if not w.save_button.isEnabled():
            raise AssertionError("Review candidate not ready to save")
        grab("ready_to_save")
        records.append(case)
    finally:
        if w._thread is not None:
            wait_finished(w, w.conversion_done, app)
        w.close()
        app.processEvents()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    metadata = {
        "feature_head": os.environ.get("GITHUB_SHA"),
        "baseline_head": BASE_SHA,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version,
        "qt": qVersion(), "qpa": app.platformName(),
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"),
        "physical_os_scheme_verified": False,
        "physical_windows11_dpi_verified": False,
        "color_scheme_source": "explicit test-only QStyleHints.setColorScheme override",
        "synthetic_source_only": True,
        "os_display_scales": {x: "NOT_EXECUTED" for x in ("100", "125", "150")},
        "cases": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp)
        data = private / "fictional_statement.csv"
        fixture(data)
        original = load_before(private)
        for phase, module in (("before", original), ("after", current_ui)):
            for scheme in ("light", "dark"):
                for width, height in SIZES:
                    take(app, module, phase, scheme, width, height,
                         args.output, data, metadata["cases"])
    (args.output / "environment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "summary.md").write_text(
        "# Bank2Odoo dark theme pilot — synthetic Windows QPA evidence\n\n"
        f"Baseline: {BASE_SHA}\nFeature: {metadata['feature_head']}\n"
        f"Cases: {len(metadata['cases'])}; before/after × light/dark × wide/narrow.\n"
        "Each case saves 8 states × 2 scroll positions at original QWidget.grab resolution.\n"
        "The NOT_PROVEN financial result is computed with a fictional two-row statement.\n"
        "ColorScheme was set by an application-only TEST override, NOT by the real OS.\n"
        "No actual Windows11 OS theme, 100/125/150% physical DPI, accountant hardware or"
        " true visual acceptance was exercised.\n",
        encoding="utf-8")
    print("DARK_PILOT_EVIDENCE:", len(metadata["cases"]),
          "cases and", len(list(args.output.glob("*.png"))),
          "lossless UI captures")


if __name__ == "__main__":
    main()
