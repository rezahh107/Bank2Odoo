"""Stage 4 evidence-only DPI override probe for the existing Bank2Odoo Qt shell.
QT_SCALE_FACTOR is a SIMULATION; Windows OS DPI and physical acceptance are NOT tested.
Run in independent Windows-QPA subprocesses with factor 1.0, 1.25 or 1.5.
No edits to production code; no real statement files; no saving/export.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

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

OUT = Path(os.environ.get("STAGE4_OUTPUT", "stage4-output")) / ("scale_sim_" + FACTOR.replace(".", "_"))
OUT.mkdir(parents=True, exist_ok=True)


def settle(app, window):
    for _ in range(12):
        app.processEvents()
        window._workspace.activate()
        window.scroll.widget().layout().activate()


def force_two_columns(window):
    """Instance-only test reflow, never redefined on production module."""
    def fixed():
        if window._workspace.direction() != QBoxLayout.Direction.LeftToRight:
            window._workspace.setDirection(QBoxLayout.Direction.LeftToRight)
            window._workspace.invalidate()
    window._reflow_workspace = fixed
    fixed()


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


def capture(app, w, scheme, width, state, position):
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
    file = "%s_%s_%s_%s.png" % (scheme, width, state, "bottom" if position else "top")
    if not grab.save(str(OUT / file), "PNG"):
        raise AssertionError("Could not save original QWidget PNG")
    return {"name": file, "png_physical_px": px, "grab_dpr": grab.devicePixelRatio(),
            "qt_window_logical": [w.width(), w.height()],
            "scroll_value": bar.value()}


def measure(app, w, scheme, width, state):
    settle(app, w)
    screen = app.primaryScreen()
    work = screen.availableGeometry()
    frame = w.frameGeometry()
    vp = w.scroll.viewport()
    base = ("select_button", "path_field", "detected", "source_unit",
            "target_unit", "precision", "factor", "approved", "convert_button", "status")
    if state == "not_proven":
        base += ("result_state", "summary", "directory_button", "output_directory", "saved_paths")
    checks = {x: inspect_control(app, w, x) for x in base}
    s = {
        "candidate_width_logical": width,
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
    }
    if w.width() != width:
        s["requested_width_realized"] = False
    else:
        s["requested_width_realized"] = True
    if s["horizontal_scroll_max"] or any(not x["fully_reachable"] for x in checks.values()):
        s["internal_geometry_result"] = "NEEDS_REVIEW"
    else:
        s["internal_geometry_result"] = "PASS_IN_TEST"
    s["images"] = [capture(app, w, scheme, width, state, 0)]
    if state == "not_proven":
        s["images"].append(capture(app, w, scheme, width, state,
                                   w.scroll.verticalScrollBar().maximum()))
    return s


def run_one(app, width, scheme, input_file):
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if scheme == "simulated_dark"
                                     else Qt.ColorScheme.Light)
    app.processEvents()
    ui.configure_application(app)
    assert_widget_font(app)
    w = ui.MainWindow()
    w.setMinimumSize(width, 480)
    force_two_columns(w)
    w.resize(width, 650)
    w.show()
    settle(app, w)
    w.resize(width, 650)
    settle(app, w)
    try:
        rows = [measure(app, w, scheme, width, "initial")]
        w.set_source(input_file)
        wait_finished(w, w.detection_done, app)
        if w.source is None:
            raise AssertionError("Synthetic file detection did not complete")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.approved.setChecked(True)
        if not (w._selected_digest and w._approved_digest == w._selected_digest):
            raise AssertionError("SHA-bound financial consent failed in test")
        rows.append(measure(app, w, scheme, width, "approval"))
        w.start_conversion()
        wait_finished(w, w.conversion_done, app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Synthetic NOT_PROVEN conversion did not complete")
        rows.append(measure(app, w, scheme, width, "not_proven"))
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
        "host": platform.platform(),
        "factor_override": FACTOR,
        "factor_is_simulation_not_os_setting": True,
        "qpa": app.platformName(),
        "font": {"family": font["family"], "version": font["version"]},
        "screen": screen_info(app),
        "test_scope": "current Qt MainWindow surrogate, not HTML v18 implemented in Qt",
    }
    cases = []
    with tempfile.TemporaryDirectory(prefix="stage4-scale-synthetic-") as temp:
        source = Path(temp) / "bank_fixture_synthetic.csv"
        fixture(source, balanced=False)
        for scheme in ("light", "simulated_dark"):
            for width in (900, 940):
                cases.extend(run_one(app, width, scheme, source))
    summary = {
        "host": host, "cases": cases,
        "window_fits_work_area_count": sum(x["fully_fits_at_some_position"] for x in cases),
        "cases_total": len(cases),
        "geometry_needs_review": sum(x["internal_geometry_result"] != "PASS_IN_TEST" for x in cases),
        "decision": "Window/workarea fit and Qt-host-scaled rendering only; actual OS scaling, Owner hardware, v18 Qt and accessibility NOT_PROVEN",
    }
    (OUT / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STAGE4_SCALE_SUMMARY " + json.dumps({
        "head": head, "factor": FACTOR, "qt_dpr": host["screen"]["qt_dpr"],
        "work_area_logical": host["screen"]["work_area_logical"],
        "os_native_dpi": host["screen"]["os_native_system_dpi"],
        "window_fit_count": summary["window_fits_work_area_count"],
        "total": summary["cases_total"],
        "geometry_needs_review": summary["geometry_needs_review"],
    }, ensure_ascii=False))
    for r in cases:
        print("STAGE4_SCALE_CASE " + json.dumps({
            k: r[k] for k in ("scheme", "candidate_width_logical", "state",
                              "window_logical", "frame_width_fits_work_area",
                              "frame_height_fits_work_area", "fully_fits_at_some_position",
                              "internal_geometry_result")
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
