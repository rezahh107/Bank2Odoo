"""Capture synthetic full-product BEFORE/AFTER Qt theme pilot states.

Only fictional bank fixtures in TemporaryDirectory. Windows hosted QPA !=
interactive Windows11 OS desktop. Explicit QStyleHints override is a SIMULATION.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import nullcontext
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
from threading import Event
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, Qt, QTimer, qVersion
from PySide6.QtGui import QFontInfo, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QStyle, QStyleOptionButton

from bank2odoo.ui import window as current_ui

BASE_SHA = "1ff8057945abacf1ae8a2532ac37b9fe9dd43361"
STATES = ("initial", "validation_error", "approval_unchecked",
          "approval_checked", "keyboard_focus", "conversion_busy",
          "not_proven_result", "ready_to_save")
SIZES = ((940, 830), (650, 520), (600, 480))


def fixture(file: Path, *, balanced: bool = False) -> None:
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
                    "کارمزد آزمایشی", "25", "0", "75" if balanced else ""])


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
    for view in ("top", "action", "bottom"):
        if view == "action":
            # Use the exact production focus/scroll behavior, not a separate
            # screenshot-only positioning heuristic with weaker margins.
            if hasattr(w, "_reveal_result"):
                w._reveal_result()
            else:
                w.scroll.ensureWidgetVisible(w.convert_button, 0, 18)
                w.scroll.ensureWidgetVisible(w.status, 0, 64)
            app.processEvents()
        elif view == "bottom":
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
            "actual_window_geometry": [w.width(), w.height()],
            "actual_viewport_width": w.scroll.viewport().width(),
            "workspace_breakpoint": getattr(w, "_workspace_breakpoint", None),
            "layout_direction": (w._workspace.direction().name
                                 if hasattr(w, "_workspace") else "legacy"),
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
    cb = w.approved
    option = QStyleOptionButton()
    option.initFrom(cb)
    rect = cb.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator, option, cb
    )
    metric = {
        "effective_style_class": type(cb.style()).__name__,
        "effective_width": cb.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth, option, cb),
        "effective_height": cb.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorHeight, option, cb),
        "rect_width": rect.width(), "rect_height": rect.height(),
    }
    # A falling 22px metric is a product-pilot STOP condition, not a
    # visually acceptable substitution from QPushButton/QSS painting.
    if phase == "after" and any(v < 22 for key, v in metric.items()
                                 if key != "effective_style_class"):
        raise AssertionError("Product approval indicator 22px metric lost: " + repr(metric))
    case = {
        "phase": phase, "requested_test_scheme": scheme,
        "approval_indicator_geometry": metric,
        "qt_effective_color_scheme": app.styleHints().colorScheme().name,
        "effective_style": app.style().objectName(),
        "resolved_font": QFontInfo(w.approved.font()).family(),
        "resolved_font_point_size": QFontInfo(w.approved.font()).pointSize(),
        "effective_dpr": w.devicePixelRatioF(),
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
        # Hold the genuine QThread worker at the conversion boundary to
        # capture a deterministic busy/cancel-request interaction. The result
        # of this cancelled phase must be discarded; then run real conversion.
        original_convert = module.convert
        entered, release = Event(), Event()

        def held_convert(path, context):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Synthetic busy capture release timed out")
            return original_convert(path, context)

        with patch.object(module, "convert", side_effect=held_convert):
            try:
                w.start_conversion()
                if not entered.wait(8):
                    raise AssertionError("Qt conversion thread never entered")
                if w._thread is None or w.busy.maximum() != 0:
                    raise AssertionError("Authentic indeterminate busy state missing")
                grab("conversion_busy")
                w.cancel_conversion()
                if "درخواست توقف" not in w.status.text() or w._stop is None:
                    raise AssertionError("Cancellation request was not recorded")
                grab("cancel_requested")
            finally:
                release.set()
            wait_finished(w, w.conversion_done, app)
        if w.result is not None or w._thread is not None:
            raise AssertionError("Cancelled active-phase result was not discarded")
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Expected synthetic NOT_PROVEN result")
        grab("not_proven_result")
        if phase == "after":
            if w.save_button.isEnabled() or "انتخاب پوشه" not in w.convert_button.text():
                raise AssertionError("Saving before private folder selection is not allowed")
        grab("ready_to_save_no_folder")
        private_folder = synthetic.parent / f"out_{phase}_{scheme}_{width}x{height}"
        private_folder.mkdir(exist_ok=True)
        # Genuine paired-save failure on a missing folder; no synthetic success text.
        w.output_directory.setText(str(private_folder / "missing"))
        w.save_files()
        wait_finished(w, w.save_done, app)
        if "خطای ذخیره" not in w.status.text() or w._saved:
            raise AssertionError("Synthetic save failure was falsely published")
        grab("save_failure")
        w.output_directory.setText(str(private_folder))
        if not w.save_button.isEnabled():
            raise AssertionError("Review candidate not ready after folder selection")
        grab("folder_selected")
        w.save_files()
        wait_finished(w, w.save_done, app)
        if not w._saved or "دو فایل ایجاد شدند" not in w.saved_paths.text():
            raise AssertionError("Actual synthetic paired save did not complete")
        grab("saved_success")
        balanced = synthetic.parent / f"balanced_{phase}_{scheme}_{width}.csv"
        fixture(balanced, balanced=True)
        w.set_source(balanced)
        wait_finished(w, w.detection_done, app)
        w.approved.setChecked(True)
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("PASS"):
            raise AssertionError("Expected real synthetic PASS result")
        grab("pass_result")
        records.append(case)
    finally:
        if w._thread is not None:
            wait_finished(w, w.conversion_done, app)
        w.close()
        app.processEvents()



def verify_native_restoration(app, root: Path, metadata: dict) -> None:
    """Audit dynamic Qt-resolved Light/Unknown roles and full-res host captures."""
    roles = ("Window", "Base", "Text", "Button", "Highlight")
    groups = ("Active", "Inactive", "Disabled")

    def effective_roles():
        palette = app.palette()
        return {
            group + "." + role: palette.color(
                getattr(QPalette.ColorGroup, group),
                getattr(QPalette.ColorRole, role),
            ).name()
            for group in groups for role in roles
        }

    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.processEvents()
    metadata["palette_restoration"] = []
    available = {x.casefold(): x for x in QStyleFactory.keys()}
    for fallback in (False, True):
        requested = "fusion" if fallback else "windows11"
        if requested not in available:
            metadata["palette_restoration"].append(
                {"style": requested, "execution": "NOT_EXECUTED",
                 "reason": "QStyle unavailable"}
            )
            continue
        style_name = available[requested]
        context = (patch.object(current_ui.QStyleFactory, "keys",
                                return_value=[style_name])
                   if fallback else nullcontext())
        with context:
            native_style = QStyleFactory.create(style_name)
            if native_style is None:
                raise RuntimeError("Unable to construct native Qt style")
            app.setStyle(native_style)
            # Test-only fresh baseline: an EMPTY Qt palette resolves all
            # color roles from the current platform/theme and QStyle.
            app.setPalette(QPalette())
            current_ui.configure_application(app)
            pilot = app._bank2odoo_appearance_pilot
            pilot.apply(_test_scheme=Qt.ColorScheme.Light)
            native_roles = effective_roles()
            for exit_scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Unknown):
                pilot.apply(_test_scheme=Qt.ColorScheme.Dark)
                dark_roles = effective_roles()
                pilot.apply(_test_scheme=exit_scheme)
                restored = effective_roles()
                if restored != native_roles:
                    mismatches = {
                        key: [value, restored[key]]
                        for key, value in native_roles.items()
                        if restored[key] != value
                    }
                    raise AssertionError(
                        f"Native palette not restored for {style_name}/"
                        f"{exit_scheme.name}: {mismatches}"
                    )
                window = current_ui.MainWindow()
                window.resize(650, 520)
                window.show()
                app.processEvents()
                frames = []
                label = f"palette_cycle_{requested}_{exit_scheme.name.lower()}"
                try:
                    snapshot(app, window, root, label, frames)
                finally:
                    window.close()
                    app.processEvents()
                metadata["palette_restoration"].append({
                    "style": style_name, "exit_scheme_test": exit_scheme.name,
                    "execution": "EXECUTED", "result": "PASS",
                    "native_roles": native_roles, "dark_roles": dark_roles,
                    "restored_roles": restored,
                    "effective_style": app.style().objectName(),
                    "real_os_transition_verified": False, "frames": frames,
                })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    metadata = {
        "actual_checkout_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "github_event_sha": os.environ.get("GITHUB_SHA"),
        "baseline_head": BASE_SHA,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version,
        "qt": qVersion(), "qpa": app.platformName(),
        "pyside6": __import__("PySide6").__version__,
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
        directory = private / ("مسیر-ساختگی-" * 6)
        directory.mkdir()
        data = directory / ("fictional_IRR_ISO_1405_" + "a" * 48 + ".csv")
        fixture(data)
        original = load_before(private)
        for phase, module in (("before", original), ("after", current_ui)):
            for scheme in ("light", "dark"):
                for width, height in SIZES:
                    take(app, module, phase, scheme, width, height,
                         args.output, data, metadata["cases"])
        verify_native_restoration(app, args.output, metadata)
    (args.output / "environment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "summary.md").write_text(
        "# Bank2Odoo dark theme pilot — synthetic Windows QPA evidence\n\n"
        f"Baseline: {BASE_SHA}\nFeature checkout HEAD: {metadata['actual_checkout_head']}\n"
        f"GitHub event SHA (may be PR merge commit): {metadata['github_event_sha']}\n"
        f"Cases: {len(metadata['cases'])}; before/after × light/dark × three window sizes.\n"
        "Each case saves 13 states × 3 actual scroll positions (top, task-action, bottom) at native QWidget.grab resolution, including cancellation request during a real held worker.\n"
        f"Native restoration audit: {len(metadata['palette_restoration'])} Qt style/scheme cases.\n"
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
