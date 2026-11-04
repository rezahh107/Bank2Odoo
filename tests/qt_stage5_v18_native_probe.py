"""Stage 5 evidence-only DPI override probe for the native Bank2Odoo UI candidate.
QT_SCALE_FACTOR is a SIMULATION; Windows OS DPI and physical acceptance are NOT tested.
Run in independent Windows-QPA subprocesses with factor 1.0, 1.25 or 1.5.
Only synthetic statements; actual two-file save to a temporary private directory.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from hashlib import sha256
from threading import Event
from unittest.mock import patch
from PySide6.QtTest import QTest

from PySide6.QtCore import Qt, QPoint, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QBoxLayout
from bank2odoo.ui import window as ui
from tests.qt_theme_pilot_capture import fixture, wait_finished
from adapters.qt_style_probe.font_runtime import initialize_font, assert_widget_font

EXPECTED_BASE = "ccec758c92b65469403533d946b69d3035c09779"
FACTOR = os.environ.get("QT_SCALE_FACTOR", "")
if FACTOR not in ("1.0", "1.25", "1.5"):
    raise SystemExit("QT_SCALE_FACTOR must be explicitly one of 1.0, 1.25, 1.5")
if os.environ.get("QT_QPA_PLATFORM", "").lower() != "windows":
    raise SystemExit("NOT_RUN: Windows QPA required")

OUT = Path(os.environ.get("STAGE5_OUTPUT", "stage5-output")) / ("scale_sim_" + FACTOR.replace(".", "_"))
OUT.mkdir(parents=True, exist_ok=True)


def settle(app, window):
    for _ in range(12):
        app.processEvents()
        window._workspace.activate()
        window.scroll.widget().layout().activate()


def inspect_control(app, window, item):
    widget = getattr(window, item)
    if not widget.isVisibleTo(window):
        return {"visible": False, "fully_reachable": False}
    viewport = window.scroll.viewport()
    scroll = window.scroll.verticalScrollBar()
    original = scroll.value()
    initial_pos = widget.mapTo(viewport, QPoint(0, 0))
    absolute_y = initial_pos.y() + original
    reveal_position = max(0, min(scroll.maximum(), absolute_y + widget.height() - viewport.height()))
    reaches = False
    for position in (0, reveal_position, scroll.maximum()):
        scroll.setValue(position)
        app.processEvents()
        p = widget.mapTo(viewport, QPoint(0, 0))
        reaches |= bool(p.x() >= 0 and p.x() + widget.width() <= viewport.width()
                        and p.y() >= 0 and p.y() + widget.height() <= viewport.height())
    scroll.setValue(original)
    app.processEvents()
    return {"visible": True, "fully_reachable": bool(reaches)}


def screen_info(app):
    screen = app.primaryScreen()
    return {
        "geometry_logical": list(screen.geometry().getRect()),
        "work_area_logical": list(screen.availableGeometry().getRect()),
        "qt_dpr": screen.devicePixelRatio(),
        "qt_logical_dpi": screen.logicalDotsPerInch(),
        "qt_physical_dpi": screen.physicalDotsPerInch(),
        "os_native_system_dpi": int(ctypes.windll.user32.GetDpiForSystem()),
        "windows_primary_physical_pixels": [
            int(ctypes.windll.user32.GetSystemMetrics(0)),
            int(ctypes.windll.user32.GetSystemMetrics(1)),
        ],
        "qt_screen_name": screen.name(),
    }


def capture(app, w, scheme, width, height, state, position):
    bar = w.scroll.verticalScrollBar()
    bar.setValue(position)
    settle(app, w)
    grab = w.grab()
    if grab.isNull():
        raise AssertionError("Null original Qt QWidget grab")
    px = [grab.width(), grab.height()]
    expected = [round(w.width() * grab.devicePixelRatio()),
                round(w.height() * grab.devicePixelRatio())]
    # Fractional DPR can introduce up to 1px rounding difference.
    if any(abs(a - b) > 2 for a, b in zip(px, expected)):
        raise AssertionError("Qt PNG dimension disagrees with widget x DPR")
    file = "%s_%sx%s_%s_%s.png" % (scheme, width, height, state, "bottom" if position else "top")
    if not grab.save(str(OUT / file), "PNG"):
        raise AssertionError("Could not save original QWidget PNG")
    return {"name": file, "sha256": sha256((OUT / file).read_bytes()).hexdigest(),
            "png_physical_px": px, "grab_dpr": grab.devicePixelRatio(),
            "qt_window_logical": [w.width(), w.height()],
            "scroll_value": bar.value()}


def measure(app, w, scheme, width, height, state):
    settle(app, w)
    screen = app.primaryScreen()
    work = screen.availableGeometry()
    frame = w.frameGeometry()
    vp = w.scroll.viewport()
    base = ("select_button", "path_field", "detected", "source_unit",
            "target_unit", "precision", "factor", "approved", "convert_button", "status")
    if state in ("not_proven", "save_error", "saved", "pass", "detail_open"):
        base += ("result_state", "summary", "directory_button", "output_directory", "saved_paths")
    if state == "saved":
        base += ("saved_csv_path", "saved_report_path")
    checks = {x: inspect_control(app, w, x) for x in base}
    s = {
        "candidate_width_logical": width,
        "candidate_height_logical": height,
        "scheme": scheme,
        "state": state,
        "window_logical": [w.width(), w.height()],
        "frame_rect_logical": list(frame.getRect()),
        "work_area_rect_logical": list(work.getRect()),
        "frame_width_fits_work_area": frame.width() <= work.width(),
        "frame_height_fits_work_area": frame.height() <= work.height(),
        "frame_position_inside_work_area": bool(work.contains(frame)),
        "fully_fits_at_some_position": frame.width() <= work.width() and frame.height() <= work.height(),
        "viewport_logical": [vp.width(), vp.height()],
        "horizontal_scroll_max": w.scroll.horizontalScrollBar().maximum(),
        "vertical_scroll_max": w.scroll.verticalScrollBar().maximum(),
        "required_controls": checks,
        "effective_font": QFontInfo(w.font()).family(),
        "qstyle": app.style().objectName(),
        "source_sha_bound_approved": bool(w._selected_digest and w._approved_digest == w._selected_digest),
        "fixed_two_column": w._workspace.direction() == QBoxLayout.Direction.LeftToRight,
        "source_detected": w.source is not None,
        "converted": w.result is not None,
        "saved_confirmed": w._saved,
        "result_balance": w.result.balance_status if w.result is not None else None,
    }
    s["requested_width_realized"] = w.width() == width
    s["requested_height_realized"] = w.height() == height
    if (not s["requested_width_realized"] or not s["requested_height_realized"]
            or not s["fixed_two_column"] or s["horizontal_scroll_max"]
            or w.scroll.widget().width() > vp.width()
            or any(not x["fully_reachable"] for x in checks.values())):
        s["internal_geometry_result"] = "NEEDS_REVIEW"
    else:
        s["internal_geometry_result"] = "PASS_IN_TEST"
    s["images"] = [capture(app, w, scheme, width, height, state, 0)]
    if state in ("not_proven", "save_error", "saved", "pass", "detail_open"):
        s["images"].append(capture(app, w, scheme, width, height, state,
                                   w.scroll.verticalScrollBar().maximum()))
    return s


def run_one(app, width, height, scheme, input_file):
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if scheme == "simulated_dark"
                                     else Qt.ColorScheme.Light)
    app.processEvents()
    ui.configure_application(app)
    assert_widget_font(app)
    w = ui.MainWindow()
    assert w.minimumWidth() == 900, "Candidate minimum must remain 900 logical px"
    w.resize(width, height)
    w.show()
    settle(app, w)
    w.resize(width, height)
    settle(app, w)
    try:
        rows = [measure(app, w, scheme, width, height, "initial")]
        w.set_source(input_file)
        wait_finished(w, w.detection_done, app)
        if w.source is None:
            raise AssertionError("Synthetic file detection did not complete")
        rows.append(measure(app, w, scheme, width, height, "detected"))
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.approved.setChecked(True)
        if not (w._selected_digest and w._approved_digest == w._selected_digest):
            raise AssertionError("SHA-bound financial consent failed in test")
        rows.append(measure(app, w, scheme, width, height, "approval"))
        # Actual Qt Space semantics, never setting the checkbox for the test.
        w.approved.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        if app.focusWidget() is not w.approved:
            raise AssertionError("Financial approval cannot receive native focus")
        QTest.keyClick(w.approved, Qt.Key.Key_Space)
        app.processEvents()
        if w.approved.isChecked() or w._approved_digest is not None:
            raise AssertionError("Native Space did not revoke SHA consent")
        QTest.keyClick(w.approved, Qt.Key.Key_Space)
        app.processEvents()
        if not (w.approved.isChecked() and w._approved_digest == w._selected_digest):
            raise AssertionError("Native Space did not restore exact-source consent")
        rows[-1]["space_consent_revoke_restore"] = True
        # Real worker with an artificially held synthetic conversion.
        entered, release = Event(), Event()
        actual_convert = ui.convert
        def held_convert(path, context):
            entered.set()
            if not release.wait(12):
                raise RuntimeError("Synthetic conversion hold timeout")
            return actual_convert(path, context)
        with patch.object(ui, "convert", side_effect=held_convert):
            try:
                w.start_conversion()
                if not entered.wait(10):
                    raise AssertionError("Qt conversion worker did not start")
                rows.append(measure(app, w, scheme, width, height, "busy"))
                w.cancel_conversion()
                if w._stop is None or not w._stop.is_set():
                    raise AssertionError("Qt worker cancellation not signaled")
                rows.append(measure(app, w, scheme, width, height, "cancel_requested"))
            finally:
                release.set()
            wait_finished(w, w.conversion_done, app)
        if w.result is not None or "توقف" not in w.status.text():
            raise AssertionError("Cancelled conversion left stale success")
        rows.append(measure(app, w, scheme, width, height, "cancel_completed"))
        # Conversion error is not a balance NOT_PROVEN result.
        with patch.object(ui, "convert", side_effect=RuntimeError("synthetic conversion failure")):
            w.start_conversion()
            wait_finished(w, w.conversion_done, app)
        if w.result is not None or not w.result_state.text().startswith("ERROR"):
            raise AssertionError("Conversion ERROR did not fail closed")
        rows.append(measure(app, w, scheme, width, height, "convert_error"))
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Actual synthetic NOT_PROVEN conversion did not complete")
        rows.append(measure(app, w, scheme, width, height, "not_proven"))
        if w.details_button.isVisible():
            w.details_button.click()
            app.processEvents()
            if not w.details.isVisible():
                raise AssertionError("Native technical disclosure did not open")
            rows.append(measure(app, w, scheme, width, height, "detail_open"))
            w.details_button.click()
        # Real paired-save worker with injected I/O failure.
        w.output_directory.setText(str(input_file.parent))
        with patch.object(ui, "save_candidate", side_effect=OSError("synthetic permission fault")):
            w.save_files()
            wait_finished(w, w.save_done, app)
        if w._saved or not w._destination_retry_blocked():
            raise AssertionError("Failed paired save incorrectly permitted success")
        rows.append(measure(app, w, scheme, width, height, "save_error"))
        with patch.object(ui.QFileDialog, "getExistingDirectory", return_value=str(input_file.parent)):
            w._browse_directory()  # An explicit confirmation, not a hidden retry.
        if w._destination_retry_blocked():
            raise AssertionError("Explicit folder confirmation did not enable safe retry")
        # Actual paired publication; never synthesized success text.
        w.save_files()
        wait_finished(w, w.save_done, app)
        if not w._saved:
            raise AssertionError("Expected real paired save of synthetic fixture")
        saved = [Path(w.saved_csv_path.text()), Path(w.saved_report_path.text())]
        if len(set(saved)) != 2 or not all(p.is_file() for p in saved):
            raise AssertionError("Paired save did not leave two distinct regular files")
        if saved[0].read_text(encoding="utf-8").splitlines()[0] != "Date,Label,Amount":
            raise AssertionError("CSV contract changed")
        row = measure(app, w, scheme, width, height, "saved")
        row["output_sha256"] = [sha256(p.read_bytes()).hexdigest() for p in saved]
        row["output_files"] = [p.name for p in saved]  # Synthetic names only.
        rows.append(row)
        # Verify a separate PASS result after an actual new source transition.
        balanced = input_file.with_name("balanced_" + str(width) + "_" + str(height) + ".csv")
        fixture(balanced, balanced=True)
        w.set_source(balanced)
        wait_finished(w, w.detection_done, app)
        if w._saved or w.result is not None or w.approved.isChecked():
            raise AssertionError("New source left stale saved/result/approval state")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.approved.setChecked(True)
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("PASS"):
            raise AssertionError("Expected independently converted synthetic PASS")
        rows.append(measure(app, w, scheme, width, height, "pass"))
        return rows
    finally:
        if w._thread is not None:
            raise AssertionError("Qt worker still active at test teardown")
        w.close()
        settle(app, w)


def main():
    if platform.system() != "Windows":
        raise SystemExit("Windows runner required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    app = QApplication([])
    if app.platformName() != "windows":
        raise AssertionError("Native Windows Qt QPA not selected")
    font = initialize_font(app, 11)
    host = {
        "git_head": head,
        "expected_main_source_sha": EXPECTED_BASE,
        "qt_version": qVersion(),
        "pyside6_version": __import__("PySide6").__version__,
        "host": platform.platform(),
        "factor_override": FACTOR,
        "factor_is_simulation_not_os_setting": True,
        "qpa": app.platformName(),
        "font": {"family": font["family"], "version": font["version"]},
        "screen": screen_info(app),
        "test_scope": "Stage 5 native Qt candidate from exact checked-out Head; v18 PROPOSED, not Owner-approved; simulated Qt scaling",
    }
    cases = []
    with tempfile.TemporaryDirectory(prefix="stage5-scale-synthetic-") as temp:
        source = Path(temp) / "bank_fixture_synthetic.csv"
        fixture(source, balanced=False)
        host["source_fixture_sha256"] = sha256(source.read_bytes()).hexdigest()
        for scheme in ("light", "simulated_dark"):
            for width in (900, 940):
                for height in (480, 650):
                    cases.extend(run_one(app, width, height, scheme, source))
    # Negative control may override the minimum only in this disposable test.
    # If everything still reads PASS, the geometry probe is not falsifiable.
    negative = ui.MainWindow()
    negative.setMinimumSize(350, 480)
    negative.resize(350, 480)
    negative.show()
    settle(app, negative)
    bad = measure(app, negative, "forced_insufficient_width", 350, 480, "negative")
    negative.close()
    if bad["internal_geometry_result"] != "NEEDS_REVIEW":
        raise AssertionError("Width negative control was incorrectly accepted")
    summary = {
        "host": host, "cases": cases, "negative_control": bad,
        "window_fits_work_area_count": sum(x["fully_fits_at_some_position"] for x in cases),
        "cases_total": len(cases),
        "candidate_heights_logical": [480, 650],
        "candidate_widths_logical": [900, 940],
        "geometry_needs_review": sum(x["internal_geometry_result"] != "PASS_IN_TEST" for x in cases),
        "decision": "Actual candidate Qt/Windows QPA and synthetic save/conversion; physical OS scaling, accountant comprehension and Owner approval NOT_PROVEN",
    }
    (OUT / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STAGE5_SCALE_SUMMARY " + json.dumps({
        "head": head, "factor": FACTOR, "qt_dpr": host["screen"]["qt_dpr"],
        "work_area_logical": host["screen"]["work_area_logical"],
        "os_native_dpi": host["screen"]["os_native_system_dpi"],
        "window_fit_count": summary["window_fits_work_area_count"],
        "total": summary["cases_total"],
        "geometry_needs_review": summary["geometry_needs_review"],
    }, ensure_ascii=False))
    for r in cases:
        print("STAGE5_SCALE_CASE " + json.dumps({
            k: r[k] for k in ("scheme", "candidate_width_logical", "candidate_height_logical", "state",
                              "window_logical", "frame_width_fits_work_area",
                              "frame_height_fits_work_area", "fully_fits_at_some_position",
                              "internal_geometry_result")
        }, ensure_ascii=False))
    if summary["geometry_needs_review"]:
        raise AssertionError("Stage5 scale/height internal geometry needs review; see persisted manifest")


if __name__ == "__main__":
    main()
