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
from bank2odoo.reporting import output as publisher
from bank2odoo.reporting.output import save_candidate as actual_save_candidate
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
    if image_file.exists():
        raise AssertionError("Duplicate native Qt evidence filename: " + name)
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



def capture_publication_outcomes(app, output, results, root):
    """Native Qt PASS + real synthetic PARTIAL/AMBIGUOUS publisher paths.

    Only test fixtures inject a second-link fault. The production publisher,
    classification, and UI rendering paths are unchanged.
    """
    for width, height in ((900, 480), (940, 650)):
        for outcome in ("COMPLETE_PAIR", "PARTIAL", "AMBIGUOUS"):
            source = root / f"fictional_{outcome}_{width}_{height}.csv"
            statement(source)
            folder = root / f"private_{outcome}_{width}_{height}"
            folder.mkdir()
            w = MainWindow()
            w.resize(width, height)
            w.show()
            app.processEvents()
            try:
                w.set_source(source)
                joined(w, w.detection_done)
                if w.source is None:
                    raise AssertionError("Fictional source detection failed")
                w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
                w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
                w.approved.setFocus()
                QTest.keyClick(w.approved, Qt.Key.Key_Space)
                if not w.approved.isChecked() or w._approved_digest != w._selected_digest:
                    raise AssertionError("Explicit keyboard approval was not SHA-bound")
                w.start_conversion()
                joined(w, w.conversion_done)
                if w.result is None or not w.result.balance_status.startswith("PASS"):
                    raise AssertionError("Fictional PASS prerequisite failed")
                w.output_directory.setText(str(folder))

                if outcome == "COMPLETE_PAIR":
                    w.save_files()
                    joined(w, w.save_done)
                else:
                    real_link = publisher.os.link
                    call_count = 0

                    def synthetic_second_link_failure(src, dst):
                        nonlocal call_count
                        call_count += 1
                        if call_count == 2:
                            if outcome == "AMBIGUOUS":
                                Path(dst).write_bytes(b"fictional independent writer bytes")
                            raise OSError("synthetic second-link publication fault")
                        return real_link(src, dst)

                    def injected_save(result, csv_path, report_path):
                        with patch.object(publisher.os, "link",
                                          side_effect=synthetic_second_link_failure):
                            return actual_save_candidate(result, csv_path, report_path)

                    with patch("bank2odoo.ui.window.save_candidate",
                               side_effect=injected_save):
                        w.save_files()
                        joined(w, w.save_done)

                observed = w.save_outcome_label.text()
                focus = app.focusWidget()
                transition_focus = (
                    focus.accessibleName() or focus.objectName()
                    or type(focus).__name__ if focus is not None else None
                )
                if not observed.startswith(outcome):
                    raise AssertionError(f"Expected {outcome}, received {observed}")
                if outcome == "COMPLETE_PAIR":
                    if not w._saved or not w.saved_path_fields.isVisible():
                        raise AssertionError("Verified full pair not presented")
                    for field in (w.saved_csv_path, w.saved_report_path):
                        if not field.isReadOnly() or field.layoutDirection() != Qt.LayoutDirection.LeftToRight:
                            raise AssertionError("Saved output path is not read-only LTR")
                        field.selectAll()
                        field.copy()
                        if app.clipboard().text() != field.text():
                            raise AssertionError("Saved output path cannot be copied")
                    if not Path(w.saved_csv_path.text()).is_file() or not Path(w.saved_report_path.text()).is_file():
                        raise AssertionError("Verified final paths are not actual files")
                    if not Path(w.saved_csv_path.text()).read_text(encoding="utf-8-sig").startswith("Date,Label,Amount"):
                        raise AssertionError("CSV output contract changed")
                else:
                    if (w._saved or w.saved_path_fields.isVisible()
                            or w.saved_csv_path.text() or w.saved_report_path.text()
                            or not w._destination_retry_blocked()
                            or w.save_button.isEnabled()
                            or w._decision_phase() != "save_error"):
                        raise AssertionError(f"{outcome} incorrectly advertised a safe full save")
                    reports = list(folder.glob("*_control.txt"))
                    csvs = list(folder.glob("*_candidate.csv"))
                    if len(reports) != 1 or len(csvs) != (1 if outcome == "AMBIGUOUS" else 0):
                        raise AssertionError(f"{outcome} disk outcome differs from actual expected files")
                    if outcome == "AMBIGUOUS" and csvs[0].read_bytes() != b"fictional independent writer bytes":
                        raise AssertionError("Independent writer's output was changed")

                capture(app, w, f"{width}x{height}_pass_{outcome.lower()}", output, results)
                results[-1]["publication_outcome"] = outcome
                results[-1]["focus_after_publication"] = transition_focus
                results[-1]["retry_blocked"] = w._destination_retry_blocked()
                results[-1]["final_paths_exposed"] = w.saved_path_fields.isVisible()
                results[-1]["disk_final_count"] = len(list(folder.glob("Bank2Odoo_*")))
            finally:
                w.close()
                app.processEvents()


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
        capture_publication_outcomes(app, output, results, tmpdir)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = {
        "head": head, "github_event_sha": os.getenv("GITHUB_SHA"),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "machine": platform.machine(), "os_release": platform.release(),
        "runner_arch": os.getenv("RUNNER_ARCH"),
        "runner_image_os": os.getenv("ImageOS"),
        "runner_image_version": os.getenv("ImageVersion"),
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
