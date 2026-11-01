"""Stage 2 evidence-only native Windows Qt responsive layout discriminator.

All captures use the actual Bank2Odoo MainWindow, pinned canonical font, and
fictional bank CSV. Controls are temporarily altered only in isolated test
instances AFTER a genuine paired save; nothing changes financial implementation.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QBoxLayout
from adapters.qt_style_probe import font_runtime

from bank2odoo.ui import window as product
from tests.qt_theme_pilot_capture import fixture, wait_finished

SIZES = ((600, 480), (650, 520), (700, 520), (740, 520), (940, 830))
SCHEMES = ("light", "dark")
ORIGINAL_CAPTIONS = (
    "اعتبارسنجی و تبدیل",
    "انتخاب پوشهٔ خصوصی خروجی…",
    "ذخیره CSV و گزارش کنترل",
    "ذخیره شد",
)
OUT = Path(os.environ["RUNNER_TEMP"]) / "bank2odoo-stage2-layout-qualification"
OUT.mkdir(parents=True, exist_ok=True)


def settle(app: QApplication, w) -> None:
    """Drain synchronous layout and queued Qt singleShot(0) recalculations."""
    for _ in range(7):
        app.processEvents()
        w._workspace.activate()
        w.scroll.widget().layout().activate()
    app.processEvents()


def measure(w, name: str, *, png: bool = False) -> dict:
    w._reflow_workspace()
    settle(QApplication.instance(), w)
    input_min = w._input_column.minimumSizeHint().width()
    result_min = w._result_column.minimumSizeHint().width()
    spacing = w._workspace.spacing()
    measured_input, measured_result, minimum_input_at_reflow, minimum_result_at_reflow = w._workspace_measurements
    requested_minimum = input_min + result_min + spacing
    record = {
        "state": name,
        "scheme": QApplication.instance().styleHints().colorScheme().name,
        "window": [w.width(), w.height()],
        "viewport_width": w.scroll.viewport().width(),
        "layout_direction": w._workspace.direction().name,
        "horizontal_scroll_max": w.scroll.horizontalScrollBar().maximum(),
        "breakpoint": w._workspace_breakpoint,
        "workspace_required_formula": {
            "input": measured_input, "result": measured_result,
            "sum_with_spacing": measured_input + measured_result + 12
        },
        "column_minimum_size_hint": {
            "input": input_min, "result": result_min,
            "spacing": spacing, "sum": requested_minimum,
            "at_last_reflow": [minimum_input_at_reflow, minimum_result_at_reflow],
        },
        "column_actual_widths": [w._input_column.width(), w._result_column.width()],
        "column_visible": [w._input_column.isVisible(), w._result_column.isVisible()],
        "convert_caption": w.convert_button.text(),
        "convert_caption_advance": w.convert_button.fontMetrics().horizontalAdvance(w.convert_button.text()),
        "convert_button_size_hint_width": w.convert_button.sizeHint().width(),
        "cancel_button_size_hint_width": w.cancel_button.sizeHint().width(),
        "cancel_visible": w.cancel_button.isVisible(),
        "directory_button_size_hint_width": w.directory_button.sizeHint().width(),
        "saved_path_fields_visible": w.saved_path_fields.isVisible(),
        "saved_csv_path_hint_width": w.saved_csv_path.sizeHint().width(),
        "saved_report_path_hint_width": w.saved_report_path.sizeHint().width(),
        "save_box_visible": w.save_box.isVisible(),
        "save_box_minimum_size_hint_width": w.save_box.minimumSizeHint().width(),
        "approved": w.approved.isChecked(),
        "approved_sha_matches": (
            w._selected_digest is not None and w._approved_digest == w._selected_digest
        ),
        "financial_balance_status": (w.result.balance_status if w.result else None),
        "paired_save_completed": w._saved,
    }
    if png:
        filename = name + ".png"
        pm = w.grab()
        if pm.isNull() or (pm.width(), pm.height()) != (
            round(w.width() * pm.devicePixelRatio()),
            round(w.height() * pm.devicePixelRatio())
        ) or not pm.save(str(OUT / filename), "PNG"):
            raise RuntimeError(f"Non-native or failed capture: {filename}")
        record["original_png"] = filename
        record["png_size"] = [pm.width(), pm.height()]
        record["png_dpr"] = pm.devicePixelRatio()
    return record


def collect(w, name, records, *, png=False):
    records.append(measure(w, name, png=png))


def simulate_minimum_hint_guard(w) -> dict:
    """Test a proposed native minimum-hint floor; NOT a product patch."""
    app = QApplication.instance()
    before = measure(w, "before_guard")
    floor = before["column_minimum_size_hint"]["sum"]
    predicate = max(before["breakpoint"], floor)
    target = (QBoxLayout.Direction.LeftToRight
              if w.scroll.viewport().width() >= predicate
              else QBoxLayout.Direction.TopToBottom)
    if w._workspace.direction() != target:
        w._workspace.setDirection(target)
        w._workspace.invalidate()
        w.scroll.widget().updateGeometry()
    settle(app, w)
    result = {
        "floor_from_native_minimum_size_hints": floor,
        "calculated_safe_breakpoint": predicate,
        "chosen_direction": target.name,
        "after_guard_direction": w._workspace.direction().name,
        "after_guard_horizontal_scroll_max": w.scroll.horizontalScrollBar().maximum(),
        "after_guard_viewport_width": w.scroll.viewport().width(),
    }
    if w._workspace.direction() != target:
        raise RuntimeError("Guarded layout direction did not persist during Qt layout pass")
    return result


def run_case(app: QApplication, scheme: str, width: int, height: int,
             folder: Path) -> dict:
    app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light
    )
    app.processEvents()
    product.configure_application(app)
    w = product.MainWindow()
    w.resize(width, height)
    w.show()
    app.processEvents()
    w.resize(width, height)  # Qualified Windows QPA first-show geometry.
    settle(app, w)
    assert (w.width(), w.height()) == (width, height)
    key = f"{scheme}_{width}x{height}"
    data = {"case": key, "scheme": scheme, "size": [width, height],
            "qstyle": app.style().objectName(),
            "resolved_font": QFontInfo(w.font()).family(),
            "resolved_font_pt": QFontInfo(w.font()).pointSize(),
            "dpr": w.devicePixelRatioF(),
            "states": [], "counterfactuals": [], "candidate": None}
    csv = folder / f"fictional_{key}.csv"
    fixture(csv)
    try:
        collect(w, key + "_initial", data["states"])
        w.set_source(csv)
        wait_finished(w, w.detection_done, app)
        if w.source is None:
            raise AssertionError("Genuine Qt fictional source detection failed")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.journal.setText("ژورنال ساختگی")
        collect(w, key + "_source_selected", data["states"])
        w.approved.setChecked(True)
        if not (w.approved.isChecked() and w._approved_digest == w._selected_digest):
            raise AssertionError("SHA-bound approval of test fixture failed")
        collect(w, key + "_approved", data["states"])
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Expected genuine fictional NOT_PROVEN candidate")
        collect(w, key + "_not_proven", data["states"])
        private_out = folder / f"private_{key}"
        private_out.mkdir()
        w.output_directory.setText(str(private_out))
        collect(w, key + "_folder_selected", data["states"])
        w.save_files()
        wait_finished(w, w.save_done, app)
        if not w._saved or "دو فایل ایجاد شدند" not in w.saved_paths.text():
            raise AssertionError("Genuine paired-file save did not complete")
        actual_saved_files = [Path(w.saved_csv_path.text()), Path(w.saved_report_path.text())]
        if not all(p.is_file() for p in actual_saved_files) or actual_saved_files[0] == actual_saved_files[1]:
            raise AssertionError("Paired-file outputs missing or incorrectly aliased")
        if w.result.balance_status.startswith("PASS") or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Synthetic incomplete balance was falsely marked PASS")
        original_balance = w.result.balance_status
        original_paths = [str(x) for x in actual_saved_files]
        collect(w, key + "_saved_legacy", data["states"], png=(width == 650))
        baseline = data["states"][-1]

        # Each visual-only mutation is reverted without running any conversion,
        # changing source identity, invalidating approval, or re-saving outputs.
        w.convert_button.setText("ذخیره CSV و گزارش کنترل")
        collect(w, key + "_saved_long_caption", data["counterfactuals"],
                png=(width == 650))
        w.convert_button.setText("انتخاب پوشهٔ خصوصی خروجی…")
        collect(w, key + "_saved_longest_caption", data["counterfactuals"])
        w.convert_button.setText("ذخیره شد")
        collect(w, key + "_saved_caption_restored", data["counterfactuals"])

        w.saved_path_fields.hide()
        collect(w, key + "_saved_paths_hidden_short_caption", data["counterfactuals"],
                png=(width == 650))
        w.saved_path_fields.show()
        collect(w, key + "_saved_paths_visible_again", data["counterfactuals"])

        data["candidate"] = simulate_minimum_hint_guard(w)
        # Native original-resolution snapshot of guarded version.
        pm = w.grab()
        name = key + "_saved_candidate_minimum_hint_guard.png"
        if pm.isNull() or not pm.save(str(OUT / name), "PNG"):
            raise RuntimeError("Native guarded capture failed")
        data["candidate"]["original_png"] = name
        data["candidate"]["png_dimensions"] = [pm.width(), pm.height()]
        data["candidate"]["png_dpr"] = pm.devicePixelRatio()

        if w.result.balance_status != original_balance or not w._saved or (
            [w.saved_csv_path.text(), w.saved_report_path.text()] != original_paths
        ):
            raise AssertionError("Counterfactual changed financial result or paired saved paths")
        if not all(p.is_file() for p in actual_saved_files):
            raise AssertionError("Counterfactual destroyed fictional saved file")
        data["confirmed_saved_files"] = 2
        data["baseline_horizontal_scroll"] = baseline["horizontal_scroll_max"]
        data["candidate_horizontal_scroll"] = data["candidate"]["after_guard_horizontal_scroll_max"]
        return data
    finally:
        w.close()
        app.processEvents()


def main():
    if sys.platform != "win32":
        raise RuntimeError("Stage 2 requires native Windows QPA")
    app = QApplication([])
    font = font_runtime.initialize_font(app, point_size=11)
    font_runtime.assert_widget_font(app)
    report = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version, "qt": qVersion(),
        "qpa": app.platformName(), "font_contract": font,
        "font_effective": QFontInfo(app.font()).family(),
        "fictional_fixtures_only": True,
        "production_code_modified": False,
        "real_os_theme_or_physical_dpi_tested": False,
        "hypothesis": "Temporary native min-size-hint floor prevents undercomputed responsive threshold",
        "cases": [],
    }
    with TemporaryDirectory(prefix="b2o_stage2_") as tmp:
        root = Path(tmp)
        for scheme in SCHEMES:
            for width, height in SIZES:
                case = run_case(app, scheme, width, height, root)
                report["cases"].append(case)
                print("QUALIFICATION_CASE", case["case"],
                      "legacy=", case["baseline_horizontal_scroll"],
                      "candidate=", case["candidate_horizontal_scroll"],
                      "bp=", case["states"][-1]["breakpoint"],
                      "min_sum=", case["states"][-1]["column_minimum_size_hint"]["sum"],
                      flush=True)

    critical = next(c for c in report["cases"] if c["case"] == "dark_650x520")
    if (critical["baseline_horizontal_scroll"] <= 0
            or critical["states"][-1]["layout_direction"] != "LeftToRight"):
        raise AssertionError(
            "Failed to reproduce original Dark 650 saved overflow; no causal qualification"
        )
    for c in report["cases"]:
        if c["resolved_font"] != "Vazirmatn" or c["resolved_font_pt"] != 11:
            raise AssertionError("Lost pinned canonical font")
    report["original_reproduction_confirmed"] = True
    report["candidate_no_new_overflow"] = all(
        c["candidate_horizontal_scroll"] == 0 for c in report["cases"]
    )
    report["caption_intervention_critical"] = [
        {"state": x["state"], "breakpoint": x["breakpoint"],
         "layout": x["layout_direction"], "horizontal": x["horizontal_scroll_max"],
         "column_minimum": x["column_minimum_size_hint"]["sum"]}
        for x in critical["counterfactuals"]
    ]
    (OUT / "qualification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("STAGE2_QUALIFICATION_SUMMARY", json.dumps({
        "critical": report["caption_intervention_critical"],
        "cases": len(report["cases"]),
        "original_reproduced": report["original_reproduction_confirmed"],
        "candidate_no_new_overflow": report["candidate_no_new_overflow"],
    }, ensure_ascii=False), flush=True)
    if not report["candidate_no_new_overflow"]:
        print("NOT_QUALIFIED: native minimum-size-hint floor insufficient on one or more cases")


if __name__ == "__main__":
    main()
