"""Native Windows Qt full-window qualification of initial action hierarchy.

Baseline, bounded A, bounded B, and production are genuine MainWindow Qt
renders. A/B only override presentation on the actual pre-repair product
instance; they do not mock widgets, approval, file reading, or conversion.
Use only fictional source data. Visual acceptance on a physical device is
NOT_PROVEN by hosted Windows QPA.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
import platform
import subprocess
import sys

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QFontInfo, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bank2odoo.ui import window as product
from tests.qt_theme_pilot_capture import fixture, load_before, wait_finished

SIZES = ((940, 830), (650, 520), (600, 480))
PHASES = ("baseline", "variant_A", "variant_B", "product")


def accent_count(w):
    return int(bool(w.select_button.styleSheet())) + int(bool(w.convert_button.styleSheet()))


def apply_qualification_variant(w, variant, scheme, phase):
    """Apply bounded style-only options to authentic, unmodified baseline Qt UI."""
    if variant not in ("variant_A", "variant_B"):
        return
    if not w.select_button.objectName():
        w.select_button.setObjectName("sourceSelection")
    dark = scheme == "dark"
    source_style = product._SOURCE_DARK_QSS if dark else product._SOURCE_LIGHT_QSS
    convert_style = product._PRIMARY_DARK_QSS if dark else product._PRIMARY_LIGHT_QSS
    # In both alternatives the enabled guidance button is visually secondary
    # until the explicit financial approval is SHA-bound and fully populated.
    w.select_button.setStyleSheet(
        source_style if variant == "variant_B" and phase == "initial" else ""
    )
    w.convert_button.setStyleSheet(
        convert_style if phase == "approved" else ""
    )


def assert_hierarchy(w, variant, phase):
    count = accent_count(w)
    if count > 1:
        raise AssertionError("Two competing accented actions")
    if variant == "baseline":
        return  # The known defect is evidence, not a passing requirement.
    if phase == "initial":
        expected = 1 if variant in ("variant_B", "product") else 0
        if bool(w.convert_button.styleSheet()) or count != expected:
            raise AssertionError("Initial conversion is visually primary or source hierarchy lost")
    elif phase == "source_selected":
        if count:
            raise AssertionError("Unapproved conversion is still accented")
    elif phase == "approved":
        if not w.convert_button.styleSheet() or w.select_button.styleSheet():
            raise AssertionError("Approved conversion was not promoted uniquely")


def capture(app, w, directory, key, state, meta):
    w.scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    images = []
    for view in ("top", "action"):
        if view == "action":
            w.scroll.ensureWidgetVisible(w.convert_button, 0, 18)
            app.processEvents()
        filename = f"{key}_{state}_{view}.png"
        pix = w.grab()
        if pix.isNull() or not pix.save(str(directory / filename), "PNG"):
            raise RuntimeError("Native Qt capture failed: " + filename)
        images.append({
            "file": filename, "native_width": pix.width(),
            "native_height": pix.height(), "dpr": pix.devicePixelRatio(),
            "scroll_y": w.scroll.verticalScrollBar().value(),
            "convert_in_viewport": w.scroll.viewport().rect().intersects(
                w.convert_button.geometry().translated(
                    w.convert_button.mapTo(w.scroll.viewport(), w.convert_button.rect().topLeft())
                    - w.convert_button.pos()
                )
            ),
        })
    meta["states"].append({
        "phase": state, "images": images,
        "select_accent": bool(w.select_button.styleSheet()),
        "convert_accent": bool(w.convert_button.styleSheet()),
        "convert_enabled": w.convert_button.isEnabled(),
        "select_enabled": w.select_button.isEnabled(),
        "approved": w.approved.isChecked(),
        "selected_digest_present": w._selected_digest is not None,
        "sha_approval_matches": (
            w._selected_digest is not None
            and w._approved_digest == w._selected_digest
        ),
        "approved_visible": w.approved.isVisible(),
        "focus_object": app.focusWidget().objectName() if app.focusWidget() else None,
        "column_direction": w._workspace.direction().name,
        "horizontal_scroll_max": w.scroll.horizontalScrollBar().maximum(),
        "actual_window": [w.width(), w.height()],
        "viewport_width": w.scroll.viewport().width(),
        "status": w.status.text(),
        "source_accessible_name": w.select_button.accessibleName(),
        "conversion_accessible_name": w.convert_button.accessibleName(),
    })


def run_case(app, ui_module, variant, scheme, width, height, source, output):
    app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if scheme == "dark" else Qt.ColorScheme.Light
    )
    app.processEvents()
    ui_module.configure_application(app)
    w = ui_module.MainWindow()
    w.resize(width, height)
    w.show()
    app.processEvents()
    key = f"{variant}_{scheme}_{width}x{height}"
    meta = {
        "variant": variant, "requested_size": [width, height],
        "scheme": scheme, "effective_style": app.style().objectName(),
        "effective_scheme_hint": app.styleHints().colorScheme().name,
        "effective_palette": {
            k: app.palette().color(getattr(QPalette.ColorRole, k)).name()
            for k in ("Window", "Base", "Text", "Button", "ButtonText", "Highlight")
        },
        "font": QFontInfo(w.font()).family(),
        "font_size_pt": QFontInfo(w.font()).pointSize(),
        "dpr": w.devicePixelRatioF(), "states": [],
    }
    try:
        apply_qualification_variant(w, variant, scheme, "initial")
        assert_hierarchy(w, variant, "initial")
        capture(app, w, output, key, "initial", meta)
        if variant == "product":
            # Genuine pointer-to-guidance path, including focus selection.
            w.scroll.ensureWidgetVisible(w.convert_button)
            app.processEvents()
            QTest.mouseClick(w.convert_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            if ("ابتدا یک گزارش بانکی" not in w.status.text()
                    or app.focusWidget() is not w.select_button or w.result is not None):
                raise AssertionError("Enabled guidance-first conversion no longer guides safely")
        w.set_source(source)
        wait_finished(w, w.detection_done, app)
        if w.source is None:
            raise AssertionError("Real Qt detection failed for fictional source")
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.journal.setText("ژورنال ساختگی")
        if w.approved.isChecked():
            raise AssertionError("Source selection implicitly approved finance")
        apply_qualification_variant(w, variant, scheme, "source_selected")
        assert_hierarchy(w, variant, "source_selected")
        capture(app, w, output, key, "source_selected", meta)
        w.approved.setChecked(True)
        if not (w._selected_digest is not None
                and w._approved_digest == w._selected_digest):
            raise AssertionError("Approval is not SHA-bound")
        apply_qualification_variant(w, variant, scheme, "approved")
        assert_hierarchy(w, variant, "approved")
        capture(app, w, output, key, "approved", meta)

        if variant == "product":
            # Additional real-widget snapshot: SHA-approved financial context
            # can still be invalid. The Qt accent must remain secondary and
            # the enabled action must guide focus to the factor field.
            w.source_unit.setCurrentIndex(w.source_unit.findData("TOMAN"))
            w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
            w.factor.setText("11")
            w.approved.setChecked(True)
            if w._approved_digest != w._selected_digest:
                raise AssertionError("Invalid-factor snapshot lacks explicit SHA approval")
            if w.convert_button.styleSheet():
                raise AssertionError("Financially invalid factor wrongly gains primary accent")
            capture(app, w, output, key, "invalid_factor", meta)
            w.convert_button.click()
            app.processEvents()
            if (w.result is not None or w._thread is not None
                    or app.focusWidget() is not w.factor
                    or "ضریب" not in w.status.text()):
                raise AssertionError("Rejected factor did not guide to its actual field")
            w.factor.setText("10")
            if w.approved.isChecked() or w.convert_button.styleSheet():
                raise AssertionError("Factor correction failed to revoke old approval")
            w.approved.setChecked(True)
            assert_hierarchy(w, variant, "approved")
            capture(app, w, output, key, "corrected_factor", meta)
        # Explicit negative control: resurrect the historically conflicting
        # bright convert style while the source is missing; detector MUST fail.
        if variant == "product":
            # Reset only the UI's input identity for this isolated style
            # mutation; never start a nonexistent source-detection worker.
            w._revoke_approval()
            w.source = None
            w._selected_digest = None
            w._invalidate()
            app.processEvents()
            if w.source is not None or w._thread is not None:
                raise AssertionError("Negative-control setup failed")
            w.convert_button.setStyleSheet(
                product._PRIMARY_DARK_QSS if scheme == "dark"
                else product._PRIMARY_LIGHT_QSS
            )
            try:
                assert_hierarchy(w, variant, "initial")
            except AssertionError:
                meta["negative_control_conflicting_convert"] = "DETECTED"
            else:
                raise AssertionError("Prominent empty-state conversion negative control escaped")
            w._apply_theme_controls()
            assert_hierarchy(w, variant, "initial")
        return meta
    finally:
        w.close()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-sha", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    report = {
        "baseline_sha": args.baseline_sha,
        "checkout_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "github_sha": os.getenv("GITHUB_SHA"),
        "platform": platform.platform(), "qt": qVersion(),
        "python": sys.version, "pyside6": __import__("PySide6").__version__,
        "qpa": app.platformName(),
        "physical_windows_11_verified": False,
        "physical_dpi_verified": False,
        "real_os_theme_change_verified": False,
        "fictional_data_only": True,
        "utc": datetime.now(timezone.utc).isoformat(),
        "cases": [],
    }
    with TemporaryDirectory() as temporary:
        home = Path(temporary)
        source = home / "fictional_mellat.csv"
        fixture(source)
        before = load_before(home, args.baseline_sha)
        for variant in PHASES:
            module = product if variant == "product" else before
            for scheme in ("light", "dark"):
                for width, height in SIZES:
                    report["cases"].append(run_case(
                        app, module, variant, scheme, width, height,
                        source, args.output
                    ))
    (args.output / "environment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "summary.md").write_text(
        "# Bank2Odoo action hierarchy — real Qt Widgets Windows QPA\n\n"
        "Variations: original main, A (demote conversion), "
        "B (accent source then promotion after financial approval), "
        "product candidate. All are genuine product Qt windows.\n\n"
        f"Base: {args.baseline_sha}; head: {report['checkout_head']}\n"
        f"Cases: {len(report['cases'])}; source selected vs SHA-approved "
        "and initial, Light/Dark, 940/650/600 requested widths.\n"
        "Negative control on product reintroduces prominent invalid conversion "
        "and must be detected. Original PNGs and effective environment in JSON.\n"
        "This does not prove physical Windows 11, alternate DPI, Persian font "
        "raster quality, or human accountant UX acceptance.\n",
        encoding="utf-8",
    )
    # Compact visual review thumbnails originate from the *saved native Qt
    # renders* above. Full-resolution originals remain in the CI artifact.
    # These prints allow independent human/LLM review without a separate
    # mockup or any bank data. Size bounded for GitHub Actions log limits.
    if os.getenv("QT_PRIMARY_LOG_PREVIEWS") == "1":
        import base64
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImage
        for variant in PHASES:
            for scheme in ("light", "dark"):
                label = f"{variant}_{scheme}_940x830_initial_top.png"
                preview = QImage(str(args.output / label))
                if preview.isNull():
                    raise RuntimeError("Missing native Qt screenshot: " + label)
                preview = preview.scaledToWidth(
                    620, Qt.TransformationMode.SmoothTransformation
                )
                data = QByteArray()
                buffer = QBuffer(data)
                if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise RuntimeError("Cannot create preview buffer")
                if not preview.save(buffer, "JPEG", 67):
                    raise RuntimeError("Cannot encode Qt preview")
                print("QT_PRIMARY_PREVIEW|" + variant + "|" + scheme + "|"
                      + base64.b64encode(bytes(data)).decode("ascii"))
    print("PRIMARY_ACTION_HIERARCHY_QT_CASES:", len(report["cases"]))
    print("NEGATIVE_CONTROL:", [
        c.get("negative_control_conflicting_convert")
        for c in report["cases"] if c["variant"] == "product"
    ])


if __name__ == "__main__":
    main()
