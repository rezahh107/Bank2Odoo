"""One connected fictional accountant journey on native Windows Qt.

No production state is assigned to manufacture outcomes; the actual UI actions,
worker, converter and publisher execute. No real bank data or output directories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, qVersion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout

from bank2odoo.reporting import output as publisher
from bank2odoo.reporting.output import control_report, output_csv, save_candidate
from bank2odoo.ui.window import MainWindow, configure_application
from tests.qt_concept_a_probe import joined
from tests.test_gui import statement


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    configure_application(app)
    window = MainWindow()
    window.resize(940, 650)
    window.show()
    app.processEvents()
    events = []

    def click(widget):
        assert widget.isVisible() and widget.isEnabled(), f"Not operable: {widget.objectName()}"
        window.scroll.ensureWidgetVisible(widget, 0, 20)
        app.processEvents()
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        app.processEvents()

    def assert_hierarchy():
        layout = window._review_layout
        action = next(i for i in range(layout.count())
                      if layout.itemAt(i).layout() is window._actions_layout)
        for widget in (window.candidate_state, window.result_state, window.summary,
                       window.save_outcome_label, window.saved_paths,
                       window.saved_path_fields, window.status):
            if widget.isVisible():
                assert 0 <= layout.indexOf(widget) < action, (
                    f"Stale or hidden warning below primary action: {widget.objectName()}"
                )
        assert window._workspace.direction() == QBoxLayout.Direction.LeftToRight
        assert window._input_column.geometry().center().x() > window._result_column.geometry().center().x()
        assert window.scroll.horizontalScrollBar().maximum() == 0

    def snapshot(stage):
        assert_hierarchy()
        name = f"{len(events) + 1:02d}_{stage}"
        image = directory / (name + ".png")
        assert not image.exists(), "Evidence must not overwrite another stage"
        pixmap = window.grab()
        assert not pixmap.isNull() and pixmap.save(str(image), "PNG")
        focus = app.focusWidget()
        events.append({
            "stage": stage,
            "source_sha_prefix": (window._selected_digest or "")[:12],
            "approved_sha_prefix": (window._approved_digest or "")[:12],
            "approval_checked": window.approved.isChecked(),
            "phase": window._decision_phase(),
            "candidate_balance": window.result.balance_status if window.result else None,
            "publisher": window.save_outcome_label.text().split(" — ", 1)[0],
            "retry_blocked": window._destination_retry_blocked(),
            "csv_name": Path(window.saved_csv_path.text()).name if window.saved_csv_path.text() else None,
            "report_name": Path(window.saved_report_path.text()).name if window.saved_report_path.text() else None,
            "focus": (focus.accessibleName() or focus.objectName() or type(focus).__name__)
                     if focus is not None else None,
            "image": image.name,
        })

    def source_picker(path, button):
        with patch("bank2odoo.ui.window.QFileDialog.getOpenFileName",
                   return_value=(str(path), "")) as picker:
            click(button)
        assert picker.call_count == 1, "Native source picker did not open once"
        joined(window, window.detection_done)
        assert window.source == path and window._selected_digest == digest(path)
        assert digest(path)[:12] in window.source_digest.text()

    def approve():
        window.source_unit.setCurrentIndex(window.source_unit.findData("IRR"))
        window.target_unit.setCurrentIndex(window.target_unit.findData("IRR"))
        window.approved.setFocus()
        QTest.keyClick(window.approved, Qt.Key.Key_Space)
        app.processEvents()
        assert window.approved.isChecked()
        assert window._approved_digest == window._selected_digest
        assert window._conversion_is_ready_for_emphasis()

    def select_folder(path):
        with patch("bank2odoo.ui.window.QFileDialog.getExistingDirectory",
                   return_value=str(path)) as picker:
            click(window.convert_button)
        assert picker.call_count == 1
        assert window.output_directory.text() == str(path)

    def verified_pair(pathset, result):
        assert len(pathset) == 2
        csv = next(p for p in pathset if p.suffix == ".csv")
        report = next(p for p in pathset if p.suffix == ".txt")
        assert csv != report and csv.is_file() and report.is_file()
        assert csv.read_bytes() == output_csv(result).encode("utf-8")
        assert csv.read_text(encoding="utf-8-sig").startswith("Date,Label,Amount\n")
        assert report.read_bytes() == control_report(result).encode("utf-8")
        assert window._saved and window.save_outcome_label.text().startswith("COMPLETE_PAIR")
        assert window.saved_path_fields.isVisible()
        assert {Path(window.saved_csv_path.text()), Path(window.saved_report_path.text())} == pathset
        for field in (window.saved_csv_path, window.saved_report_path):
            assert field.isReadOnly() and field.layoutDirection() == Qt.LayoutDirection.LeftToRight
            field.selectAll()
            field.copy()
            assert app.clipboard().text() == field.text()
        return csv, report

    with tempfile.TemporaryDirectory(prefix="B2O_ConnectedPilot_") as temp:
        root = Path(temp)
        first = root / "fictional_missing_balance.csv"
        second = root / "fictional_complete_balance.csv"
        folder = root / "private"
        folder.mkdir()
        statement(first, not_proven=True)
        statement(second)
        assert digest(first) != digest(second)
        try:
            # Journey A: source picker -> explicit Space approval -> conversion.
            source_picker(first, window.select_button)
            first_sha = window._selected_digest
            assert not window.approved.isChecked() and window._approved_digest is None
            approve()
            click(window.convert_button)
            joined(window, window.conversion_done)
            first_result = window.result
            assert first_result is not None and first_result.sha256 == first_sha
            assert first_result.balance_status.startswith("NOT_PROVEN")
            assert "NOT_PROVEN" in window.result_state.text()
            assert "تأیید حسابداری نیست" in window.candidate_state.text()
            snapshot("first_not_proven")

            select_folder(folder)
            real_link = publisher.os.link
            links = 0

            def second_link_failure(src, dst):
                nonlocal links
                links += 1
                if links == 2:
                    raise OSError("synthetic interruption after first final link")
                return real_link(src, dst)

            def interrupted_publication(result, csv, report):
                with patch.object(publisher.os, "link", side_effect=second_link_failure):
                    return save_candidate(result, csv, report)

            with patch("bank2odoo.ui.window.save_candidate",
                       side_effect=interrupted_publication):
                click(window.convert_button)
                joined(window, window.save_done)
            assert links == 2, "Synthetic failure did not reach the real second link"
            assert window.save_outcome_label.text().startswith("PARTIAL")
            assert window._decision_phase() == "save_error"
            assert not window._saved and window._destination_retry_blocked()
            assert not window.save_button.isEnabled()
            assert not window.saved_path_fields.isVisible()
            assert not window.saved_csv_path.text() and not window.saved_report_path.text()
            partial_reports = list(folder.glob("Bank2Odoo_*_control.txt"))
            assert len(partial_reports) == 1 and not list(folder.glob("Bank2Odoo_*_candidate.csv"))
            partial_bytes = partial_reports[0].read_bytes()
            assert partial_bytes == control_report(first_result).encode("utf-8")
            snapshot("first_partial_no_final_paths")

            # Canceling the prompted folder reconfirmation must NOT retry.
            with patch("bank2odoo.ui.window.QFileDialog.getExistingDirectory",
                       return_value="") as cancelled:
                click(window.convert_button)
            assert cancelled.call_count == 1
            assert window._destination_retry_blocked() and not window._saved
            assert list(folder.glob("Bank2Odoo_*_control.txt")) == partial_reports
            assert not list(folder.glob("Bank2Odoo_*_candidate.csv"))
            snapshot("first_retry_cancelled")

            # Explicitly reconfirm the same folder, then let the actual publisher run.
            select_folder(folder)
            assert not window._destination_retry_blocked()
            assert window._approved_digest == first_sha and window.result is first_result
            click(window.convert_button)
            joined(window, window.save_done)
            first_pair = {Path(window.saved_csv_path.text()), Path(window.saved_report_path.text())}
            csv1, report1 = verified_pair(first_pair, first_result)
            assert report1 != partial_reports[0]
            assert partial_reports[0].read_bytes() == partial_bytes
            snapshot("first_complete_pair")
            untouched = {p.name: p.read_bytes() for p in folder.glob("Bank2Odoo_*")}
            assert len(untouched) == 3

            # Journey B: same window, real next-statement action, distinct bytes.
            source_picker(second, window.convert_button)
            second_sha = window._selected_digest
            assert second_sha != first_sha and window.source == second
            assert not window.approved.isChecked() and window._approved_digest is None
            assert window.result is None and not window._saved
            assert not window.saved_path_fields.isVisible()
            assert not window.saved_csv_path.text() and not window.saved_report_path.text()
            assert not window.save_outcome_label.text()
            assert "NOT_PROVEN" not in window.result_state.text()
            assert "COMPLETE_PAIR" not in window.status.text()
            assert csv1.name not in window.saved_paths.text()
            assert first_sha[:12] not in window.source_digest.text()
            assert second_sha[:12] in window.source_digest.text()
            snapshot("second_fresh_unapproved")

            # Main action may guide to approval, but cannot silently grant it.
            click(window.convert_button)
            assert window._thread is None and window.result is None
            assert not window.approved.isChecked() and window._approved_digest is None
            assert app.focusWidget() is window.approved
            approve()
            assert window._approved_digest == second_sha
            snapshot("second_explicitly_approved")
            click(window.convert_button)
            joined(window, window.conversion_done)
            second_result = window.result
            assert second_result is not None and second_result.sha256 == second_sha
            assert second_result.balance_status.startswith("PASS")
            assert "PASS" in window.result_state.text()
            assert "NOT_PROVEN" not in window.result_state.text()
            snapshot("second_pass")
            if not window.output_directory.text().strip():
                select_folder(folder)
            click(window.convert_button)
            joined(window, window.save_done)
            second_pair = {Path(window.saved_csv_path.text()), Path(window.saved_report_path.text())}
            csv2, report2 = verified_pair(second_pair, second_result)
            assert not (first_pair & second_pair)
            assert first_sha[:10] in csv1.name and second_sha[:10] in csv2.name
            assert {p.name: p.read_bytes() for p in folder.glob("Bank2Odoo_*")
                    if p.name in untouched} == untouched
            assert len(list(folder.glob("Bank2Odoo_*"))) == 5
            snapshot("second_complete_pair")

            record = {
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "qpa": app.platformName(),
                "qt": qVersion(),
                "sha_prefixes": [first_sha[:12], second_sha[:12]],
                "scenario_A": "PASS",
                "scenario_B": "PASS",
                "publication_failure": "PARTIAL (synthetic second-link interruption)",
                "reconfirmation": "explicit picker; canceled attempt did not retry",
                "first_file_bytes_preserved_after_second": True,
                "same_qt_window": True,
                "screenshots": len(events),
                "events": events,
                "human_accountant_usability": "NOT_PROVEN",
                "physical_windows_x64_dpi_font_screenreader": "NOT_PROVEN",
            }
            (directory / "pilot.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print("CONNECTED_OPERATOR_PILOT", record["head"], "PASS",
                  "events", len(events), "QPA", app.platformName())
        finally:
            window.close()
            app.processEvents()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
