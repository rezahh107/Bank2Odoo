"""Windows-QPA Stage 2 responsive regression, against current or pinned pre-repair MainWindow.

Fictional bank sources only. Reproduces baseline, runs native Qt pipeline,
proves real CSV/report existence and guarded geometry, and preserves the
read-only/source-SHA/accountant-review semantics. Not a physical-device test.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QBoxLayout
from adapters.qt_style_probe import font_runtime
from bank2odoo.ui import window as current_ui
from tests.qt_theme_pilot_capture import fixture, wait_finished

BASELINE_SHA = "f58743742851787c55b5c9145257f035940985be"
SIZES = ((600, 480), (650, 520), (700, 520), (710, 520),
         (720, 520), (730, 520), (740, 520), (940, 830))


def settle(app, w):
    """Consume native Qt deferred layout turns and detect unstable directions."""
    observed = []
    for _ in range(7):
        app.processEvents()
        w._workspace.activate()
        w.scroll.widget().layout().activate()
        observed.append(w._workspace.direction().name)
    app.processEvents()
    return observed


def rect_measure(w, state, *, strict, screenshot=None):
    app = QApplication.instance()
    w._reflow_workspace()
    turns = settle(app, w)
    root = w.scroll.widget().layout().contentsMargins()
    input_min = w._input_column.minimumSizeHint().width()
    result_min = w._result_column.minimumSizeHint().width()
    native = (input_min + result_min + w._workspace.spacing()
              + root.left() + root.right())
    estimated = sum(w._workspace_measurements[:2]) + 12
    viewport = w.scroll.viewport().width()
    direction = w._workspace.direction()
    horizontal = w.scroll.horizontalScrollBar().maximum()
    rec = {
        "state": state,
        "requested_vs_actual_widget": [w.width(), w.height()],
        "viewport": viewport, "horizontal_scroll_max": horizontal,
        "direction": direction.name, "turns": turns,
        "breakpoint": w._workspace_breakpoint,
        "estimated_text_requirement": estimated,
        "native_minimum": native,
        "column_minimum": [input_min, result_min],
        "workspace_spacing": w._workspace.spacing(),
        "parent_horizontal_margins": [root.left(), root.right()],
        "caption": w.convert_button.text(),
        "caption_width": w.convert_button.sizeHint().width(),
        "save_group_visible": w.save_box.isVisible(),
        "saved_path_fields_visible": w.saved_path_fields.isVisible(),
        "sha_approval_matches": (
            w._selected_digest is not None and
            w._approved_digest == w._selected_digest
        ),
        "balance": w.result.balance_status if w.result else None,
        "paired_saved": w._saved,
        "horizontal_scrollbar_policy": w.scroll.horizontalScrollBarPolicy().name,
    }
    if strict:
        assert w._workspace_breakpoint == max(estimated, native), (state, rec)
        assert (direction == QBoxLayout.Direction.LeftToRight) == (viewport >= w._workspace_breakpoint), (state, rec)
        assert direction != QBoxLayout.Direction.LeftToRight or viewport >= native, (state, rec)
        assert horizontal == 0, (state, rec)
        assert len(set(turns)) == 1, ("Reflow oscillation", state, turns)
    if screenshot:
        pm = w.grab()
        assert not pm.isNull()
        assert [pm.width(), pm.height()] == [
            round(w.width() * pm.devicePixelRatio()),
            round(w.height() * pm.devicePixelRatio()),
        ]
        assert pm.save(str(screenshot), "PNG")
        rec["original_png"] = screenshot.name
        rec["png_dimensions"] = [pm.width(), pm.height()]
        rec["png_dpr"] = pm.devicePixelRatio()
    return rec


def baseline_window(folder):
    raw = subprocess.check_output([
        "git", "show", f"{BASELINE_SHA}:bank2odoo/ui/window.py"
    ])
    file = folder / "unmodified_main_window.py"
    file.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("unmodified_main_window", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def negative_missing_parent_margins(w):
    """Falsify the native minimum sum without the outer layout margins."""
    app = QApplication.instance()
    measured = rect_measure(w, "negative_control_pre", strict=True)
    weak = max(
        measured["estimated_text_requirement"],
        sum(measured["column_minimum"]) + measured["workspace_spacing"],
    )
    viewport = measured["viewport"]
    if not (weak <= viewport < measured["native_minimum"]):
        return {"eligible": False, "weak_breakpoint": weak}
    w._workspace.setDirection(QBoxLayout.Direction.LeftToRight)
    w._workspace.invalidate()
    w.scroll.widget().updateGeometry()
    settle(app, w)
    overflow = w.scroll.horizontalScrollBar().maximum()
    assert overflow > 0, ("Weak margin-free guard wrongly thought sufficient", measured)
    w._reflow_workspace()
    settle(app, w)
    assert w.scroll.horizontalScrollBar().maximum() == 0
    return {"eligible": True, "weak_breakpoint": weak, "forced_two_column_overflow": overflow}


def run_case(app, module, scheme, width, height, folder, out, *, strict=True):
    app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light
    )
    app.processEvents()
    module.configure_application(app)
    w = module.MainWindow()
    w.resize(width, height)
    w.show()
    app.processEvents()
    w.resize(width, height)
    settle(app, w)
    assert (w.width(), w.height()) == (width, height)
    key = f"{scheme}_{width}x{height}"
    record = {"key": key, "qstyle": app.style().objectName(),
              "font": QFontInfo(w.font()).family(),
              "point_size": QFontInfo(w.font()).pointSize(),
              "states": [], "negative": None}
    assert record["font"] == "Vazirmatn" and record["point_size"] == 11
    def capture(stage, *, png=False):
        target = (out / f"{key}_{stage}.png") if png else None
        record["states"].append(rect_measure(w, stage, strict=strict, screenshot=target))

    src = folder / f"fictional_{key}.csv"
    fixture(src)
    try:
        capture("initial", png=(width in (650, 940)))
        w.set_source(src)
        wait_finished(w, w.detection_done, app)
        assert w.source is not None
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        # Historical pinned baseline requires Journal; the integrated GUI does not.
        if hasattr(w, "journal"):
            w.journal.setText("ژورنال ساختگی")
        capture("source_selected")
        w.approved.setChecked(True)
        assert w._approved_digest == w._selected_digest
        capture("approved")
        if strict and width == 650:
            # Real worker, held at the conversion boundary, then cancelled:
            # no partial result is allowed to become saveable.
            entered, release = Event(), Event()
            real_convert = module.convert
            def held_convert(path, context):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Bounded busy test timed out")
                return real_convert(path, context)
            with patch.object(module, "convert", side_effect=held_convert):
                try:
                    w.start_conversion()
                    assert entered.wait(8)
                    capture("busy")
                    w.cancel_conversion()
                    capture("cancel_requested")
                finally:
                    release.set()
                wait_finished(w, w.conversion_done, app)
            assert w.result is None
            capture("cancel_completed")
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        assert w.result is not None and w.result.balance_status.startswith("NOT_PROVEN")
        capture("not_proven")
        if strict and width == 650:
            target_folder = folder / f"private_{key}"
            target_folder.mkdir()
            w.output_directory.setText(str(target_folder / "missing"))
            w.save_files()
            wait_finished(w, w.save_done, app)
            assert not w._saved and "خطای ذخیره" in w.status.text()
            capture("save_failure")
        else:
            target_folder = folder / f"private_{key}"
            target_folder.mkdir()
        w.output_directory.setText(str(target_folder))
        capture("folder_selected")
        w.save_files()
        wait_finished(w, w.save_done, app)
        assert w._saved and "دو فایل ایجاد شدند" in w.saved_paths.text()
        actual_files = [Path(w.saved_csv_path.text()), Path(w.saved_report_path.text())]
        assert all(p.is_file() for p in actual_files) and actual_files[0] != actual_files[1]
        assert w.result.balance_status.startswith("NOT_PROVEN")
        original_paths = [str(p) for p in actual_files]
        capture("saved_success", png=(width in (650, 700, 720, 940)))
        if strict:
            for caption in ("ذخیره CSV و گزارش کنترل", "انتخاب پوشهٔ خصوصی خروجی…", "ذخیره شد"):
                w.convert_button.setText(caption)
                capture("caption_" + str(len(caption)))
            assert w.saved_path_fields.isVisible() and w.save_box.isVisible()
            record["negative"] = negative_missing_parent_margins(w)
            capture("restored")
            if width in (650, 700, 720):
                for resize_width in (740, width, 940, width):
                    w.resize(resize_width, height)
                    settle(app, w)
                    capture(f"resize_{resize_width}")
                # Controlled synthetic theme hint transition on the same window.
                new_scheme = (Qt.ColorScheme.Light if scheme == "dark" else Qt.ColorScheme.Dark)
                app.styleHints().setColorScheme(new_scheme)
                app.processEvents()
                module.configure_application(app)
                settle(app, w)
                capture("theme_switched")
                app.styleHints().setColorScheme(
                    Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light
                )
                app.processEvents()
                module.configure_application(app)
                settle(app, w)
                capture("theme_restored")
            assert [w.saved_csv_path.text(), w.saved_report_path.text()] == original_paths
            assert all(p.is_file() for p in actual_files)
            assert w.result.balance_status.startswith("NOT_PROVEN")
            if width == 650:
                balanced = folder / f"balanced_{key}.csv"
                fixture(balanced, balanced=True)
                w.set_source(balanced)
                wait_finished(w, w.detection_done, app)
                w.approved.setChecked(True)
                w.start_conversion()
                wait_finished(w, w.conversion_done, app)
                assert w.result is not None and w.result.balance_status.startswith("PASS")
                capture("pass")
        return record
    finally:
        w.close()
        app.processEvents()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("baseline", "repaired"), required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    assert sys.platform == "win32"
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    font = font_runtime.initialize_font(app, point_size=11)
    font_runtime.assert_widget_font(app)
    report = {"mode": args.mode, "utc": datetime.now(timezone.utc).isoformat(),
              "baseline_sha": BASELINE_SHA, "font": font,
              "qpa": app.platformName(), "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="b2o_stage2_repair_") as tmp:
        folder = Path(tmp)
        module = (baseline_window(folder) if args.mode == "baseline" else current_ui)
        if args.mode == "baseline":
            schemes_sizes = [("dark", 650, 520), ("dark", 700, 520),
                             ("light", 700, 520)]
        else:
            schemes_sizes = [(scheme, *size) for scheme in ("light", "dark") for size in SIZES]
        for scheme, width, height in schemes_sizes:
            case = run_case(app, module, scheme, width, height, folder, args.output,
                            strict=(args.mode == "repaired"))
            report["scenarios"].append(case)
            saved = next(s for s in case["states"] if s["state"] == "saved_success")
            print("STAGE2", args.mode, case["key"], "saved_overflow",
                  saved["horizontal_scroll_max"], "bp", saved["breakpoint"],
                  "native", saved["native_minimum"], flush=True)

    if args.mode == "baseline":
        critical = report["scenarios"][0]
        saved = next(s for s in critical["states"] if s["state"] == "saved_success")
        assert saved["horizontal_scroll_max"] == 76, saved
        other = [next(s for s in c["states"] if s["state"] == "saved_success")
                 for c in report["scenarios"][1:]]
        assert all(s["horizontal_scroll_max"] > 0 for s in other), other
    else:
        negatives = [c["negative"] for c in report["scenarios"] if c["negative"] and c["negative"]["eligible"]]
        assert negatives and all(n["forced_two_column_overflow"] > 0 for n in negatives)
        assert all(s["horizontal_scroll_max"] == 0
                   for c in report["scenarios"] for s in c["states"])
    (args.output / f"{args.mode}_measurements.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STAGE2_RESULT", args.mode, len(report["scenarios"]), "PASS", flush=True)


if __name__ == "__main__":
    main()
