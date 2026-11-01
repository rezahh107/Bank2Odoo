"""Evidence-only Windows Qt native QPA screen/window geometry probe.

No production changes or financial input. A full-size QWidget.grab is
valid only when post-show QWidget and PNG pixel sizes both match.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication
from adapters.qt_style_probe import font_runtime
from bank2odoo.ui.window import MainWindow, configure_application


def rect(r):
    return [r.x(), r.y(), r.width(), r.height()]


def win32_metrics():
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
    r = RECT()
    ok = bool(user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0))
    return {
        "SM_CXSCREEN": user32.GetSystemMetrics(0),
        "SM_CYSCREEN": user32.GetSystemMetrics(1),
        "SPI_GETWORKAREA": ([r.left, r.top, r.right - r.left,
                              r.bottom - r.top] if ok else None),
    }


def screen_record(s):
    return {
        "name": s.name(),
        "geometry": rect(s.geometry()),
        "available_geometry": rect(s.availableGeometry()),
        "virtual_geometry": rect(s.virtualGeometry()),
        "available_virtual_geometry": rect(s.availableVirtualGeometry()),
        "device_pixel_ratio": s.devicePixelRatio(),
        "logical_dpi": [s.logicalDotsPerInchX(), s.logicalDotsPerInchY()],
        "physical_dpi": [s.physicalDotsPerInchX(), s.physicalDotsPerInchY()],
    }


def measure(w, app, name, out, *, save=False):
    app.processEvents()
    h = w.windowHandle()
    pm = w.grab() if w.isVisible() else None
    record = {
        "stage": name,
        "widget_size": [w.width(), w.height()],
        "widget_geometry": rect(w.geometry()),
        "frame_geometry": rect(w.frameGeometry()),
        "widget_minimum_size": [w.minimumWidth(), w.minimumHeight()],
        "widget_maximum_size": [w.maximumWidth(), w.maximumHeight()],
        "window_handle_geometry": rect(h.geometry()) if h else None,
        "window_handle_screen": h.screen().name() if h and h.screen() else None,
        "widget_dpr": w.devicePixelRatioF(),
        "grab_size": [pm.width(), pm.height()] if pm else None,
        "grab_dpr": pm.devicePixelRatio() if pm else None,
    }
    if save and pm is not None:
        path = out / (name + ".png")
        if pm.isNull() or not pm.save(str(path), "PNG"):
            raise RuntimeError(f"Unable to save native QWidget.grab {path}")
        record["original_png"] = path.name
    return record


def main():
    out = Path(os.environ["RUNNER_TEMP"]) / "bank2odoo-stage1" / "geometry-diagnostic"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    font = font_runtime.initialize_font(app, point_size=11)
    font_runtime.assert_widget_font(app)
    report = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "qt": qVersion(),
        "pyside6": __import__("PySide6").__version__,
        "qpa": app.platformName(),
        "font": font,
        "win32": win32_metrics(),
        "screens": [screen_record(s) for s in app.screens()],
        "requested_vs_actual": [],
        "real_os_theme_tested": False,
        "physical_dpi_tested": False,
    }
    for scheme in ("light", "dark"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if scheme == "light" else Qt.ColorScheme.Dark)
        app.processEvents()
        configure_application(app)
        for requested in ((940, 830), (650, 520), (600, 480)):
            w = MainWindow()
            w.resize(*requested)
            group = {"scheme": scheme, "requested": list(requested),
                     "qstyle": app.style().objectName(),
                     "effective_font": QFontInfo(w.font()).family(),
                     "font_pt": QFontInfo(w.font()).pointSize(),
                     "stages": []}
            try:
                group["stages"].append(measure(w, app, "before_show", out))
                w.show()
                app.processEvents()
                group["stages"].append(measure(w, app, "after_show", out,
                                               save=requested == (940, 830)))
                w.resize(*requested)
                app.processEvents()
                group["stages"].append(measure(w, app, "post_show_resize", out,
                                               save=requested == (940, 830)))
                w.setGeometry(0, 0, *requested)
                app.processEvents()
                group["stages"].append(measure(w, app, "post_show_setgeometry", out,
                                               save=requested == (940, 830)))
                font_runtime.assert_widget_font(w)
                report["requested_vs_actual"].append(group)
            finally:
                w.close()
                app.processEvents()
    (out / "geometry.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print("QT_GEOMETRY_REPORT=" + json.dumps({
        "screens": report["screens"], "win32": report["win32"],
        "cases": [{"scheme": c["scheme"], "requested": c["requested"],
                   "stages": [{"stage": s["stage"], "widget": s["widget_size"],
                               "grab": s["grab_size"]} for s in c["stages"]]}
                  for c in report["requested_vs_actual"]]},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
