"""Diagnostic-only PR #8 missing-input guidance visibility matrix.

No bank file is parsed and no conversion or private write is authorized.
Synthetic source Path/digest are only in-memory UI state used to reach missing
field scenarios; production conversion/approval validation is not overridden.
Run in hosted Windows QPA for screenshots, never infer physical acceptance.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QGroupBox

from bank2odoo.ui.window import MainWindow, configure_application


SCENARIOS = (
    ("source", "select_button", "گزارش بانکی"),
    ("source_unit", "source_unit", "واحد پول فایل بانک"),
    ("target_unit", "target_unit", "واحد پول ژورنال مقصد"),
    ("journal", "journal", "نام ژورنال"),
    ("factor", "factor", "ضریب تبدیل"),
    ("approval", "approved", "تأیید صریح"),
)
SIZES = ((940, 830), (650, 520), (600, 480))


def screen_coverage(widget, viewport) -> dict:
    position = widget.mapTo(viewport, QPoint(0, 0))
    box = QRect(position, widget.size())
    intersection = box.intersected(viewport.rect())
    covered = max(0, intersection.width()) * max(0, intersection.height())
    area = max(1, box.width() * box.height())
    return {
        "viewport_rectangle": [position.x(), position.y(), box.width(), box.height()],
        "coverage": round(covered / area, 4),
        "in_view": covered > 0,
        "fully_in_view": covered >= area,
    }


def configure_case(window: MainWindow, case: str) -> None:
    if case == "source":
        return
    # Synthetic sentinel: no path is opened; every scenario must exit before
    # the conversion thread/financial engine starts.
    window.source = Path(tempfile.gettempdir()) / "__synthetic_pr8_diagnostic__.csv"
    window._selected_digest = "synthetic_only_never_read"
    window.path_field.setText("Synthetic UI fixture / no real statement")
    window.detected.setText("بانک/قالب: ورودی مصنوعی فقط برای آزمون رابط")
    if case == "source_unit":
        return
    window.source_unit.setCurrentIndex(window.source_unit.findData(
        "TOMAN" if case == "factor" else "IRR"))
    if case == "target_unit":
        return
    window.target_unit.setCurrentIndex(window.target_unit.findData("IRR"))
    if case == "journal":
        return
    window.journal.setText("ژورنال آزمایشی")
    if case == "factor":
        # Intentional synthetic binding to exercise the missing-factor path.
        window.approved.setChecked(True)
        assert window._approved_digest == window._selected_digest
    # For approval, checked remains False (the safe default).


def visible_context(window: MainWindow, target) -> list[str]:
    view = window.scroll.viewport()
    target_y = target.mapTo(view, QPoint(0, 0)).y()
    labels = []
    for widget in window.findChildren(QLabel):
        if widget is window.status:
            continue
        rect = screen_coverage(widget, view)
        y = widget.mapTo(view, QPoint(0, 0)).y()
        if rect["in_view"] and (target_y - 160 <= y <= target_y + 160):
            labels.append(widget.text())
    for group in window.findChildren(QGroupBox):
        rect = screen_coverage(group, view)
        if rect["in_view"] and target.parentWidget() in group.findChildren(type(target)):
            labels.append("SECTION: " + group.title())
    return labels[:12]


def main() -> None:
    output = Path(os.environ["RUNNER_TEMP"]) / "bank2odoo-pr8-guidance"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    configure_application(app)
    records = []

    for width, height in SIZES:
        for name, attr, keyword in SCENARIOS:
            window = MainWindow()
            window.resize(width, height)
            configure_case(window, name)
            window.show()
            for _ in range(5):
                app.processEvents()
            # Simulate an accountant reaching and clicking Convert, from the
            # bottom of the form, not invoking start_conversion in isolation.
            window.scroll.ensureWidgetVisible(window.convert_button)
            app.processEvents()
            before = window.scroll.verticalScrollBar().value()
            QTest.mouseClick(window.convert_button, Qt.MouseButton.LeftButton)
            for _ in range(5):
                app.processEvents()
            expected = getattr(window, attr)
            focused = app.focusWidget()
            target_view = screen_coverage(expected, window.scroll.viewport())
            status_view = screen_coverage(window.status, window.scroll.viewport())
            screenshot = f"guidance-{width}x{height}-{name}.png"
            assert window.grab().save(str(output / screenshot)), screenshot
            rec = {
                "size_requested": [width, height],
                "size_actual": [window.width(), window.height()],
                "scenario": name,
                "expected_target": attr,
                "focused_control": (
                    attr if focused is expected
                    else focused.objectName() if focused is not None else None),
                "focus_is_expected": focused is expected,
                "scroll_before_click": before,
                "scroll_after_focus": window.scroll.verticalScrollBar().value(),
                "scroll_maximum": window.scroll.verticalScrollBar().maximum(),
                "target_visibility": target_view,
                "status_visibility": status_view,
                "status_text": window.status.text(),
                "contains_expected_guidance": keyword in window.status.text(),
                "target_label": expected.text() if hasattr(expected, "text") else
                    expected.currentText() if hasattr(expected, "currentText") else "",
                "placeholder": expected.placeholderText()
                    if hasattr(expected, "placeholderText") else "",
                "adjacent_visible_labels": visible_context(window, expected),
                "thread_started": window._thread is not None,
                "result_created": window.result is not None,
                "screenshot": screenshot,
                "style": app.style().objectName(),
                "font": app.font().family(),
            }
            records.append(rec)
            print("GUIDANCE_CASE", json.dumps(rec, ensure_ascii=False))
            window.close()
            window.deleteLater()
            app.processEvents()

    report = {
        "reviewed_pr_sha": "2d7cebff71f33929794f04437c451525b8b774bb",
        "platform": os.getenv("QT_QPA_PLATFORM"),
        "limits": [
            "Windows hosted QPA, not a physical accountant desktop",
            "In-memory synthetic source/digest used only for early-exit input errors",
            "Visibility geometry and screenshot do not replace comprehension testing",
            "No financial processing, bank files, Odoo or private save exercised",
        ],
        "records": records,
    }
    (output / "guidance-matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GUIDANCE_MATRIX", json.dumps({
        "cases": len(records),
        "focus_matches": sum(r["focus_is_expected"] for r in records),
        "status_visible": sum(r["status_visibility"]["in_view"] for r in records),
        "target_visible": sum(r["target_visibility"]["in_view"] for r in records),
        "target_fully_visible": sum(r["target_visibility"]["fully_in_view"] for r in records),
    }))
    if any((not r["focus_is_expected"] or not r["contains_expected_guidance"]
            or r["thread_started"] or r["result_created"]) for r in records):
        raise AssertionError("Diagnostic invariants failed; see full artifact records")


if __name__ == "__main__":
    main()
