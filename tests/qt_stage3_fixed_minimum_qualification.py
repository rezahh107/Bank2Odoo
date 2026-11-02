"""Stage 3 fixed desktop two-column qualification; test-only, synthetic and Windows QPA.
No production module editing. Both pinned main Journal and PR20 journal-free UIs
use actual MainWindow objects; test-only bound _reflow_workspace holds two columns.
"""
from __future__ import annotations

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
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt, qVersion
from PySide6.QtGui import QFont, QFontInfo, QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication, QBoxLayout
from adapters.qt_style_probe import font_runtime
from bank2odoo.ui import window as journal_free
from tests.qt_theme_pilot_capture import fixture, wait_finished
from tests.qt_stage1_geometry_probe import win32_metrics, screen_record
from tests.qt_stage3_geometry_classifier import classify_geometry

MAIN_SHA = "e0f50ab8605024896bf6975050fb4034b874514e"
PR20_SHA = "aa4362adfa8cd3e6e2873c8b36de79ce8183e3bd"
WIDTHS = (800, 840, 900, 940, 980)
HEIGHT = 620
SCHEMES = ("light", "dark")


def pinned_main(folder):
    raw = subprocess.check_output(["git", "show", MAIN_SHA + ":bank2odoo/ui/window.py"])
    file = folder / "stage3_pinned_main_window.py"
    file.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("stage3_pinned_main_window", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settle(app, w):
    for _ in range(9):
        app.processEvents()
        w._workspace.activate()
        w.scroll.widget().layout().activate()
    assert w._workspace.direction() == QBoxLayout.Direction.LeftToRight


def force_two_columns(w):
    """Only test object patch. A production layout/algorithm is never changed."""
    def guard():
        if w._workspace.direction() != QBoxLayout.Direction.LeftToRight:
            w._workspace.setDirection(QBoxLayout.Direction.LeftToRight)
            w._workspace.invalidate()
    w._reflow_workspace = guard
    guard()


def can_reveal(app, w, target):
    if not target.isVisibleTo(w):
        return None
    w.scroll.ensureWidgetVisible(target, 4, 8)
    app.processEvents()
    rect = QRect(target.mapTo(w.scroll.viewport(), QPoint(0, 0)), target.size())
    area = w.scroll.viewport().rect()
    # The target must be at least partially inside the usable vertical viewport.
    # Horizontal containment checked separately except for intentionally scrollable line edits.
    return {
        "in_viewport": rect.intersects(area),
        "horizontally_contained": rect.left() >= area.left() and rect.right() <= area.right(),
        "rectangle": [rect.x(), rect.y(), rect.width(), rect.height()],
    }


def capture(app, w, folder, tag, view):
    bar = w.scroll.verticalScrollBar()
    if view == "top":
        bar.setValue(0)
    elif view == "action":
        w.scroll.ensureWidgetVisible(w.convert_button, 0, 18)
        w.scroll.ensureWidgetVisible(w.result_state, 0, 64)
    else:
        bar.setValue(bar.maximum())
    app.processEvents()
    pm = w.grab()
    if pm.isNull():
        raise AssertionError("Null QWidget.grab")
    expected = [round(v * pm.devicePixelRatio()) for v in (w.width(), w.height())]
    assert [pm.width(), pm.height()] == expected, (expected, pm.width(), pm.height())
    name = tag + "_" + view + ".png"
    assert pm.save(str(folder / name), "PNG")
    return {"file": name, "png_px": [pm.width(), pm.height()],
            "qt_dpr": pm.devicePixelRatio(), "view": view, "vertical_pos": bar.value()}


def measure(app, w, stage):
    w._reflow_workspace()
    settle(app, w)
    margins = w.scroll.widget().layout().contentsMargins()
    input_hint = w._input_column.minimumSizeHint().width()
    result_hint = w._result_column.minimumSizeHint().width()
    required = input_hint + result_hint + w._workspace.spacing() + margins.left() + margins.right()
    viewport = w.scroll.viewport()
    horizontal = w.scroll.horizontalScrollBar()
    values = {
        "state": stage,
        "widget": [w.width(), w.height()],
        "frame": [w.frameGeometry().width(), w.frameGeometry().height()],
        "viewport": [viewport.width(), viewport.height()],
        "content": [w.scroll.widget().width(), w.scroll.widget().height()],
        "input_min_hint": input_hint, "result_min_hint": result_hint,
        "workspace_spacing": w._workspace.spacing(),
        "root_margins": [margins.left(), margins.right()],
        "required_content_width": required,
        "horizontal_overflow_logical_px": max(0, w.scroll.widget().width() - viewport.width()),
        "horizontal_scroll_max": horizontal.maximum(),
        "horizontal_bar_hidden": not horizontal.isVisible(),
        "vertical_scroll_max": w.scroll.verticalScrollBar().maximum(),
        "layout": w._workspace.direction().name,
        "approval": w.approved.isChecked(),
        "approval_source_bound": w._selected_digest is not None and w._approved_digest == w._selected_digest,
        "balance": w.result.balance_status if w.result is not None else None,
        "result": w.result is not None, "saved": w._saved,
        "primary_label": w.convert_button.text(),
        "font": QFontInfo(w.font()).family(),
        "heading_font_weight": int(QFontInfo(w.heading.font()).weight()),
        "primary_font_weight": int(QFontInfo(w.convert_button.font()).weight()),
        "button_width": w.convert_button.width(),
        "column_actual_widths": [w._input_column.width(), w._result_column.width()],
        "screenshots": [],
    }
    # Scroll both directions; test actual viewport reachability, not merely the scrollbar policy.
    checks = {"approved": w.approved, "primary": w.convert_button,
              "source": w.select_button, "status": w.status}
    if w.result is not None:
        checks.update({"balance": w.result_state, "save_folder": w.directory_button,
                       "saved_paths": w.saved_paths})
    if w._saved:
        checks.update({"csv_path": w.saved_csv_path, "report_path": w.saved_report_path})
    values["required_controls"] = list(checks)
    values["reachable"] = {key: can_reveal(app, w, child) for key, child in checks.items()}
    return values


def long_nested(folder, prefix):
    target = folder
    for i in range(2):
        target = target / (prefix + "_" + str(i) + "_" + ("x" * 25))
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_case(app, module, variant, scheme, width, root, folder):
    app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light)
    app.processEvents()
    module.configure_application(app)
    font_runtime.assert_widget_font(app)
    w = module.MainWindow()
    w.setMinimumSize(width, 480)
    force_two_columns(w)
    w.resize(width, HEIGHT)
    w.show()
    app.processEvents()
    w.resize(width, HEIGHT)
    settle(app, w)
    assert [w.width(), w.height()] == [width, HEIGHT], (variant, scheme, width, w.size())
    assert QFontInfo(w.font()).family() == "Vazirmatn"
    key = f"{variant}_{scheme}_{width}"
    rec = {"variant": variant, "scheme": scheme, "width": width,
           "height": HEIGHT, "qstyle": app.style().objectName(),
           "font": QFontInfo(w.font()).family(),
           "minimum_width_after_show": w.minimumWidth(),
           "journal_present": hasattr(w, "journal"),
           "states": []}
    assert rec["journal_present"] == (variant == "main_journal")
    decisive = width in (800, 940)
    def state(name):
        data = measure(app, w, name)
        views = ()
        if name in ("initial", "saved_success"):
            views = ("top",) if name == "initial" else ("action", "bottom")
        if decisive and name in ("invalid_context", "approval_checked", "busy",
                                 "cancel_requested", "cancel_completed",
                                 "not_proven", "save_failure", "pass"):
            views = ("action", "bottom") if name in ("not_proven", "save_failure", "pass") else ("top",)
        for view in views:
            data["screenshots"].append(capture(app, w, root, key + "_" + name, view))
        rec["states"].append(data)

    source_folder = long_nested(folder / key, "source")
    source = source_folder / ("synthetic_bank_statement_" + "L" * 50 + ".csv")
    fixture(source)
    try:
        state("initial")
        w.set_source(source)
        wait_finished(w, w.detection_done, app)
        assert w.source == source and w._selected_digest is not None
        state("source_selected")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("TOMAN"))
        w.factor.setText("3")
        if hasattr(w, "journal"):
            w.journal.setText("ژورنال ساختگی")
        state("invalid_context")
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.factor.setText("1")
        state("approval_unchecked")
        w.approved.setChecked(True)
        assert w._approved_digest == w._selected_digest
        state("approval_checked")
        if decisive:
            entered, release = Event(), Event()
            real_convert = module.convert
            def held_convert(path, context):
                entered.set()
                if not release.wait(12):
                    raise RuntimeError("Synthetic busy boundary timed out")
                return real_convert(path, context)
            with patch.object(module, "convert", side_effect=held_convert):
                try:
                    w.start_conversion()
                    assert entered.wait(10), "Background conversion did not start"
                    state("busy")
                    w.cancel_conversion()
                    state("cancel_requested")
                finally:
                    release.set()
                wait_finished(w, w.conversion_done, app)
            assert w.result is None
            state("cancel_completed")
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        assert w.result is not None and w.result.balance_status.startswith("NOT_PROVEN")
        state("not_proven")
        target = long_nested(folder / key, "private_output")
        if decisive:
            w.output_directory.setText(str(target / "missing"))
            w.save_files()
            wait_finished(w, w.save_done, app)
            assert not w._saved and w.result is not None
            state("save_failure")
        w.output_directory.setText(str(target))
        state("folder_selected")
        w.save_files()
        wait_finished(w, w.save_done, app)
        assert w._saved
        paths = [Path(w.saved_csv_path.text()), Path(w.saved_report_path.text())]
        assert paths[0] != paths[1] and all(x.is_file() for x in paths)
        state("saved_success")
        if decisive:
            balanced = source_folder / ("balanced_" + "L" * 50 + ".csv")
            fixture(balanced, balanced=True)
            w.set_source(balanced)
            wait_finished(w, w.detection_done, app)
            w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
            w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
            w.factor.setText("1")
            if hasattr(w, "journal"):
                w.journal.setText("ژورنال ساختگی")
            w.approved.setChecked(True)
            assert w._approved_digest == w._selected_digest
            w.start_conversion()
            wait_finished(w, w.conversion_done, app)
            assert w.result is not None and w.result.balance_status.startswith("PASS")
            state("pass")
        return rec
    finally:
        assert w._thread is None
        w.close()
        app.processEvents()


def negative_case(app, module, folder):
    module.configure_application(app)
    w = module.MainWindow()
    w.setMinimumWidth(500)  # Deliberate test-only negative below every candidate.
    force_two_columns(w)
    w.resize(500, HEIGHT)
    w.show()
    app.processEvents()
    w.resize(500, HEIGHT)
    settle(app, w)
    try:
        m = measure(app, w, "forced_below_native_required")
        assert m["required_content_width"] > m["viewport"][0]
        assert (m["horizontal_scroll_max"] > 0
                or m["horizontal_overflow_logical_px"] > 0), m
        m["screenshots"] = [capture(app, w, folder, "negative_500", "top")]
        return m
    finally:
        w.close()
        app.processEvents()


def make_sheet(folder, report, variant, scheme):
    # Preview-only composites; never replace native full-resolution originals.
    width, height = 5 * 275, 3 * 225
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ECEFF2"))
    painter = QPainter(image)
    painter.setPen(QColor("#17212B"))
    painter.setFont(QFont("Arial", 10))
    for index, candidate in enumerate(WIDTHS):
        match = next(c for c in report["cases"] if c["variant"] == variant
                     and c["scheme"] == scheme and c["width"] == candidate)
        for row, (state, view) in enumerate((("initial", "top"),
                                              ("saved_success", "action"),
                                              ("saved_success", "bottom"))):
            item = next(s for s in match["states"] if s["state"] == state)
            cap = next(x for x in item["screenshots"] if x["view"] == view)
            pix = QImage(str(folder / cap["file"]))
            assert not pix.isNull()
            x, y = 275 * index + 8, 225 * row + 25
            painter.drawText(x, y - 6, f"{candidate}px / {state} / {view}")
            scaled = pix.scaled(259, 190, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            painter.drawImage(x, y, scaled)
    painter.end()
    name = "contact_" + variant + "_" + scheme + ".png"
    assert image.save(str(folder / name), "PNG")
    return name


def main():
    assert sys.platform == "win32", "Windows Qt QPA is required"
    out = Path(os.environ.get("STAGE3_EVIDENCE", "stage3-evidence")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    font = font_runtime.initialize_font(app, point_size=11)
    font_runtime.assert_widget_font(app)
    assert font["regular_weight"] == 400 and font["semibold_weight"] >= 600
    summary = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Stage 3 design qualification only — not a product implementation",
        "source_heads": {"main": MAIN_SHA, "journal_free_pr20": PR20_SHA},
        "qualification_test_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "test_override": "Instance-level _reflow_workspace force QBoxLayout.LeftToRight; setMinimumSize(candidate,480)",
        "machine": {"platform": platform.platform(), "python": sys.version,
                    "qt": qVersion(), "pyside6": __import__("PySide6").__version__,
                    "qpa": app.platformName(), "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "unset"),
                    "win32": win32_metrics(),
                    "screens": [screen_record(s) for s in app.screens()]},
        "font": font,
        "light_source": "Qt synthetic colorScheme Light on Windows QPA; light native-QStyle branch",
        "dark_source": "Qt synthetic colorScheme Dark, Fusion and pilot palette; NOT physical OS dark mode",
        "target_work_area_resolutions": [[1024, 768], [1366, 768], [1920, 1080]],
        "physical_screen_dpi_proof": False,
        "cases": [], "negative": None, "contact_sheets": []}
    with tempfile.TemporaryDirectory(prefix="bank2odoo_stage3_") as tmp:
        folder = Path(tmp)
        main_module = pinned_main(folder)
        for variant, module in (("main_journal", main_module),
                                ("journal_free", journal_free)):
            for scheme in SCHEMES:
                for width in WIDTHS:
                    case = run_case(app, module, variant, scheme, width, out, folder)
                    case["geometry_classification"] = classify_geometry(case["states"])
                    summary["cases"].append(case)
                    worst = max(s["horizontal_scroll_max"] for s in case["states"])
                    req = max(s["required_content_width"] for s in case["states"])
                    print("STAGE3_CASE", variant, scheme, width, "required_max", req,
                          "overflow_scroll_max", worst, flush=True)
        summary["negative"] = negative_case(app, journal_free, out)
    summary["negative"]["geometry_classification"] = classify_geometry([summary["negative"]])
    for variant in ("main_journal", "journal_free"):
        for scheme in SCHEMES:
            summary["contact_sheets"].append(make_sheet(out, summary, variant, scheme))
    rows = []
    rows.append("# Stage 3 Windows Qt QPA measurements (not physical desktop approval)")
    rows.append("")
    rows.append("Source main: `" + MAIN_SHA + "`; PR20: `" + PR20_SHA + "`.")
    rows.append("Light uses test-set Qt Light hint and native-style branch; Dark uses a test-set Dark hint and simulated Fusion palette. Both have authentic QWidget grabs on a Windows hosted runner.")
    rows.append("Comparison configuration overrides only the live test window's reflow to two columns; production stays unchanged. Logical pixels; PNG dimensions and Qt DPR recorded per capture.")
    rows.append("GEOMETRY_PASS is assigned only by tests.qt_stage3_geometry_classifier.classify_geometry over every required control in every measured state; missing and partially clipped controls fail closed.")
    rows.append("")
    rows.append("| Variant | Scheme | Minimum width | Max required | Viewport | Max horizontal scrollbar overflow | All key controls reachable | Geometry status |")
    rows.append("|---|---|---:|---:|---:|---:|---|---|")
    for c in summary["cases"]:
        states = c["states"]
        overflow = max(s["horizontal_scroll_max"] for s in states)
        viewport = min(s["viewport"][0] for s in states)
        required = max(s["required_content_width"] for s in states)
        verdict = c["geometry_classification"]
        rows.append(f"| {c['variant']} | {c['scheme']} | {c['width']} | {required} | {viewport} | {overflow} | {verdict['all_key_controls_reachable']} | {verdict['status']} |")
    rows.append("")
    rows.append("Negative forced 500 px: scrollbar overflow = "
                + str(summary["negative"]["horizontal_scroll_max"]) + " logical px; classification = "
                + summary["negative"]["geometry_classification"]["status"] + ".")
    rows.append("Visual readability/density, physical DPI scaling (100/125/150%), real OS theme and target-accountant acceptance remain NOT_PROVEN pending specialist review.")
    rows.append("Screenshots are genuine, unmodified QWidget.grab PNGs; contact sheets are preview composites only.")
    (out / "MEASUREMENTS.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary["negative"]["geometry_classification"]["status"] != "NOT_QUALIFIED":
        raise AssertionError("500px control must remain NOT_QUALIFIED; evidence was saved")
    print("STAGE3_COMPLETE", len(summary["cases"]), "cases;",
          len(list(out.glob("*.png"))), "PNG files; negative",
          summary["negative"]["horizontal_scroll_max"], flush=True)


if __name__ == "__main__":
    main()
