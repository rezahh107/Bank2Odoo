"""Native Windows Qt Concept A probe; synthetic only; physical DPI is NOT_PROVEN.

Captures actual Qt Widgets (not HTML) with width and height, QScreen work area,
frame fit, RTL column order, scroll reachability, fonts and primary focus.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, Qt, QTimer, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout

from bank2odoo.ui.window import MainWindow, configure_application
from tests.test_gui import statement


def joined(window, signal):
    if window._thread is None:
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    signal.connect(loop.quit)
    timer.start(20000)
    loop.exec()
    if not timer.isActive() or window._thread is not None:
        raise RuntimeError("Real fictional worker did not join")
    timer.stop()


def rect(r):
    return [r.x(), r.y(), r.width(), r.height()]


def capture(app, window, name, directory, report):
    window.show()
    app.processEvents()
    window._reflow_workspace()
    app.processEvents()
    # Include focus/scroll reachability as well as horizontal geometry.
    visible_controls = [
        window.convert_button, window.approved, window.path_field,
        window.candidate_state, window.result_state, window.summary,
        window.save_outcome_label, window.saved_paths,
        window.output_directory, window.saved_csv_path, window.saved_report_path,
    ]
    reachable = {}
    for widget in visible_controls:
        if not widget.isVisible():
            continue
        window.scroll.ensureWidgetVisible(widget, 0, 10)
        app.processEvents()
        p = widget.mapTo(window.scroll.viewport(), widget.rect().center())
        reachable[widget.accessibleName() or widget.objectName() or type(widget).__name__] = (
            window.scroll.viewport().rect().contains(p)
        )
    window.scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    screen = window.windowHandle().screen() if window.windowHandle() else window.screen()
    available = screen.availableGeometry() if screen else app.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    right = window._input_column.geometry()
    left = window._result_column.geometry()
    after_scroll_hmax = window.scroll.horizontalScrollBar().maximum()
    internal = (window._workspace.direction() == QBoxLayout.Direction.LeftToRight
                and right.center().x() > left.center().x()
                and after_scroll_hmax == 0 and all(reachable.values()))
    # Native Qt geometry/reading-order discriminator, not widget existence.
    layout = window._review_layout
    action_index = next(i for i in range(layout.count())
                        if layout.itemAt(i).layout() is window._actions_layout)
    evidence = (window.candidate_state, window.result_state, window.summary,
                window.save_outcome_label, window.saved_paths,
                window.saved_path_fields, window.status)
    evidence_first = all(layout.indexOf(widget) < action_index
                         for widget in evidence if widget.isVisible())
    support_after = (layout.indexOf(window.metrics_panel) > action_index
                     and layout.indexOf(window.save_box) > action_index)
    # The window may be larger than the logical work area at simulated scale.
    frame_fits = frame.width() <= available.width() and frame.height() <= available.height()
    image_file = directory / (name + ".png")
    pix = window.grab()
    if pix.isNull() or not pix.save(str(image_file), "PNG"):
        raise RuntimeError("Native original-resolution Qt PNG capture failed: " + name)
    report.append({
        "case": name, "screen": screen.name() if screen else None,
        "work_area_logical": rect(available),
        "frame_geometry": rect(frame), "window_geometry": rect(window.geometry()),
        "minimum_size_hint": [window.minimumSizeHint().width(),
                              window.minimumSizeHint().height()],
        "minimum_size": [window.minimumWidth(), window.minimumHeight()],
        "right_column": rect(right), "left_column": rect(left),
        "column_metrics": list(window._workspace_measurements),
        "horizontal_overflow": after_scroll_hmax,
        "control_reachable": reachable, "internal_reachability": internal,
        "evidence_before_action": evidence_first,
        "secondary_after_action": support_after,
        "frame_fits_work_area": frame_fits,
        "font": QFontInfo(window.font()).family(),
        "font_point_size": QFontInfo(window.font()).pointSize(),
        "dpr": window.devicePixelRatioF(),
        "primary": window.convert_button.text(),
        "primary_enabled": window.convert_button.isEnabled(),
        "approval_checked": window.approved.isChecked(),
        "source_sha_bound": (
            window._selected_digest is not None and
            window._approved_digest == window._selected_digest
        ),
        "result": window.result.balance_status if window.result else None,
        "verified_pair": window._saved,
        "image": image_file.name,
        "native_image": [pix.width(), pix.height()],
    })
    if not internal:
        raise AssertionError("Concept A native internal RTL/scroll/focus geometry failed: " + name)
    if not evidence_first or not support_after:
        raise AssertionError("Concept A evidence/action hierarchy failed: " + name)


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    configure_application(app)
    results = []
    with tempfile.TemporaryDirectory(prefix="B2O_ConceptA_Fictional_") as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "fictional_mellat.csv"
        statement(source, not_proven=True)
        dest = tmpdir / "private"
        dest.mkdir()
        for width, height in ((900, 480), (900, 650), (940, 480), (940, 650)):
            w = MainWindow()
            w.resize(width, height)
            w.show()
            app.processEvents()
            label = f"{width}x{height}"
            try:
                capture(app, w, label + "_initial", output, results)
                w.set_source(source)
                joined(w, w.detection_done)
                capture(app, w, label + "_financial_unapproved", output, results)
                w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
                w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
                w.convert_button.click()
                if w.approved.isChecked():
                    raise AssertionError("Navigation automatically approved financial context")
                w.approved.setFocus()
                QTest.keyClick(w.approved, Qt.Key.Key_Space)
                if not w.approved.isChecked() or w._approved_digest != w._selected_digest:
                    raise AssertionError("Explicit SHA-bound keyboard approval failed")
                capture(app, w, label + "_approved", output, results)
                w.start_conversion()
                joined(w, w.conversion_done)
                if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
                    raise AssertionError("Genuine fictional NOT_PROVEN candidate missing")
                capture(app, w, label + "_not_proven", output, results)
                w.output_directory.setText(str(dest / "missing"))
                w.save_files()
                joined(w, w.save_done)
                if w._saved or w._decision_phase() != "save_error":
                    raise AssertionError("Unsafe failed save erroneously treated as complete")
                capture(app, w, label + "_save_failure", output, results)
                w.output_directory.setText(str(dest))
                w.save_files()
                joined(w, w.save_done)
                if not w._saved or not w.saved_csv_path.text() or not w.saved_report_path.text():
                    raise AssertionError("Complete private pair was not verified")
                capture(app, w, label + "_complete_pair", output, results)
                with patch("bank2odoo.ui.window.QFileDialog.getOpenFileName",
                           return_value=("", "")) as picker:
                    w.convert_button.click()
                if picker.call_count != 1 or not w._saved:
                    raise AssertionError("Canceled next source discarded complete pair")
            finally:
                w.close()
                app.processEvents()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = {
        "head": head, "github_event_sha": os.getenv("GITHUB_SHA"),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "pyside": __import__("PySide6").__version__, "qt": qVersion(),
        "qpa": app.platformName(), "qt_scale_factor": os.getenv("QT_SCALE_FACTOR"),
        "visual_reference": "B2O-CRE-S5-001 Concept A; images are native Qt, not HTML",
        "simulated_scale_not_physical_windows_dpi": True,
        "physical_accountant_task": "NOT_PROVEN",
        "screen_reader_announcement": "NOT_PROVEN",
        "states": results,
    }
    (output / "measurements.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("CONCEPT_A_NATIVE_QT", head, "cases", len(results),
          "internal", sum(x["internal_reachability"] for x in results),
          "frame_fit", sum(x["frame_fits_work_area"] for x in results))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
