"""Standalone, source-data-free Qt styling diagnosis. No Bank2Odoo imports."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QCoreApplication, QPoint, Qt, qVersion
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QGuiApplication, QImage, QPainter, QPen, QPalette, QPixmap, QPolygonF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStyle, QStyleFactory, QStyleOptionButton, QVBoxLayout, QWidget,
)

TOKENS = {
    "dark": dict(primary="#8DCFF8", text="#14344A", disabled="#303A44",
                 disabled_text="#A7B4BD", hover="#A6DBFA", focus="#B5D4FF",
                 check="#85CDF5", window="#151A21", surface="#202831",
                 body_text="#EAF1F7"),
    "light": dict(primary="#1466C4", text="#FFFFFF", disabled="#C7D0DA",
                  disabled_text="#6D7C8C", hover="#0F56A8", focus="#145DB8",
                  check="#1466C4", window="#F4F6FA", surface="#FFFFFF",
                  body_text="#1D2A37"),
}
STATES = ("normal", "hover", "focus", "pressed", "disabled")
METHODS = ("default", "palette", "qss")
WIDGETS = ("button", "checkbox_unchecked", "checkbox_checked")
ROLE_NAMES = ("Button", "ButtonText", "Highlight", "HighlightedText", "Window", "Base", "Text")
DIFF_THRESHOLD = 12


def rgb(value):
    c = QColor(value)
    return (c.red(), c.green(), c.blue())


def hex_rgb(pixel):
    return QColor(pixel[0], pixel[1], pixel[2]).name().upper()


def distance(a, b):
    if a is None or b is None:
        return None
    return round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))), 2)


def luminance(color):
    channels = [v / 255 for v in color]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    if a is None or b is None:
        return None
    l1, l2 = sorted((luminance(a), luminance(b)), reverse=True)
    return round((l1 + .05) / (l2 + .05), 3)


def pixels(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return image.width(), image.height(), bytes(image.constBits())


def difference(a, b):
    wa, ha, ba = pixels(a)
    wb, hb, bb = pixels(b)
    if wa != wb or ha != hb:
        return {"changed": True, "count": -1, "fraction": 1, "reason": "different_dimensions"}
    count = sum(1 for i in range(0, len(ba), 4)
                if max(abs(ba[i + j] - bb[i + j]) for j in range(3)) > DIFF_THRESHOLD)
    fraction = count / max(1, wa * ha)
    return {"changed": count >= 12 and fraction >= .001, "count": count,
            "fraction": round(fraction, 6), "reason": "pixel_threshold"}


def px(image, x, y):
    c = image.pixelColor(max(0, min(image.width() - 1, x)),
                         max(0, min(image.height() - 1, y)))
    return (c.red(), c.green(), c.blue())


def pick_text(image, widget_type, background, target_text):
    # Only sample the label area, excluding indicator, border, and widget corners.
    w, h = image.width(), image.height()
    x0, x1 = (30, w - 30) if widget_type == "button" else (18, max(19, w - 46))
    counts = Counter()
    for y in range(max(1, h // 4), max(2, h * 3 // 4)):
        for x in range(x0, x1):
            color = px(image, x, y)
            if distance(color, background) is not None and distance(color, background) > 45:
                # Exact RGB clusters are preferred; ignore very rare AA fringe colors.
                counts[color] += 1
    if not counts:
        return None
    eligible = [(color, n) for color, n in counts.items() if n >= 2]
    if not eligible:
        eligible = list(counts.items())
    # Favor populated high-contrast text clusters; target only breaks close ties.
    return max(eligible, key=lambda item:
               (item[1] * min(contrast(item[0], background) or 1, 8),
                -distance(item[0], target_text)))[0]


def sample(widget, kind, pixmap, theme, state):
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    dpr = pixmap.devicePixelRatio()
    w, h = image.width(), image.height()
    if kind == "button":
        background = px(image, int(15 * dpr), h // 2)
    else:
        option = QStyleOptionButton()
        option.initFrom(widget)
        rect = widget.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,
                                             option, widget)
        # Physical pixel coordinates: Qt geometry is logical, grab is physical.
        cx, cy = int(rect.center().x() * dpr), int(rect.center().y() * dpr)
        background = px(image, cx, cy)
    tokens = TOKENS[theme]
    desired_text = rgb(tokens["disabled_text" if state == "disabled" else "text"]
                       if kind == "button" else tokens["body_text"])
    text = pick_text(image, kind, background, desired_text)
    if kind == "button":
        target = rgb(tokens["disabled" if state == "disabled" else
                            "hover" if state == "hover" else "primary"])
    else:
        target = rgb(tokens["check"]) if kind == "checkbox_checked" else None
    return {"bg": background, "bg_hex": hex_rgb(background),
            "text": text, "text_hex": hex_rgb(text) if text else "",
            "target": target, "target_hex": hex_rgb(target) if target else "",
            "distance": distance(background, target),
            "contrast": contrast(background, text),
            "physical_size": [w, h], "dpr": dpr}


def base_palette(app, theme):
    # Same controlled theme baseline for all three methods: *no button/checkbox
    # overrides*. Document this app-level experimental background intervention.
    t = TOKENS[theme]
    p = QPalette(app.style().standardPalette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, key in ((QPalette.ColorRole.Window, "window"),
                          (QPalette.ColorRole.Base, "window"),
                          (QPalette.ColorRole.WindowText, "body_text"),
                          (QPalette.ColorRole.Text, "body_text")):
            p.setColor(group, role, QColor(t[key]))
    app.setPalette(p)


def widget_palette(widget, theme):
    t = TOKENS[theme]
    p = QPalette(widget.palette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in (
            (QPalette.ColorRole.Button, t["primary"]),
            (QPalette.ColorRole.ButtonText, t["text"]),
            (QPalette.ColorRole.Highlight, t["check"]),
            (QPalette.ColorRole.HighlightedText, t["text"]),
            (QPalette.ColorRole.Window, t["window"]),
            (QPalette.ColorRole.Base, t["surface"]),
            (QPalette.ColorRole.Text, t["body_text"]),
        ):
            p.setColor(group, role, QColor(color))
    for role, color in (
        (QPalette.ColorRole.Button, t["disabled"]),
        (QPalette.ColorRole.ButtonText, t["disabled_text"]),
        (QPalette.ColorRole.Highlight, t["disabled"]),
        (QPalette.ColorRole.HighlightedText, t["disabled_text"]),
        (QPalette.ColorRole.Window, t["window"]),
        (QPalette.ColorRole.Base, t["surface"]),
        (QPalette.ColorRole.Text, t["disabled_text"]),
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    widget.setPalette(p)


def make_check_asset(output, theme):
    # An actual tick mark is essential; replacing the native indicator with
    # a colored square without a check would be a misleading "success".
    path = output / ("check_" + theme + ".png")
    img = QImage(18, 18, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(TOKENS[theme]["text"]), 2.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    from PySide6.QtCore import QPointF
    painter.drawPolyline(QPolygonF([QPointF(3, 9), QPointF(7.4, 13), QPointF(15, 4)]))
    painter.end()
    if not img.save(str(path)):
        raise RuntimeError("Cannot write checkbox tick asset")
    return path.as_posix()


def apply_method(widget, kind, method, theme, check_asset):
    t = TOKENS[theme]
    if method == "palette":
        widget_palette(widget, theme)
    if method != "qss":
        return
    if kind == "button":
        widget.setStyleSheet(
            "QPushButton {"
            f"background-color: {t['primary']}; color: {t['text']};"
            "border: 2px solid transparent; border-radius: 9px;"
            "padding: 9px 18px; min-height: 43px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {t['hover']}; }}"
            f"QPushButton:focus {{ border: 2px solid {t['focus']}; }}"
            f"QPushButton:pressed {{ background-color: {t['focus']}; }}"
            f"QPushButton:disabled {{ background-color: {t['disabled']};"
            f"color: {t['disabled_text']}; }}"
        )
    elif kind.startswith("checkbox"):
        widget.setStyleSheet(
            f"QCheckBox {{ color: {t['body_text']}; min-height: 52px; }}"
            "QCheckBox::indicator { width: 19px; height: 19px;"
            f"background-color: {t['surface']}; border: 2px solid {t['disabled_text']};"
            "border-radius: 4px; }"
            f"QCheckBox::indicator:checked {{ background-color: {t['check']};"
            f"border-color: {t['check']}; image: url('{check_asset}'); }}"
            f"QCheckBox::indicator:hover {{ border-color: {t['focus']}; }}"
            f"QCheckBox:focus {{ color: {t['body_text']}; }}"
            f"QCheckBox:focus::indicator {{ border-color: {t['focus']}; }}"
            f"QCheckBox::indicator:disabled {{ background-color: {t['disabled']};"
            f"border-color: {t['disabled_text']}; }}"
        )
    else:  # surface
        widget.setStyleSheet(
            f"QFrame#probeSurface {{ background-color: {t['surface']};"
            "border-radius: 9px; border: 1px solid transparent; }}"
        )


def make_host(theme, method, check_asset):
    host = QWidget()
    host.setObjectName("probeHost")
    host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    host.setWindowTitle("Qt styling mechanism probe — Bank2Odoo")
    host.setMinimumSize(520, 290)
    host.setAutoFillBackground(True)
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(28, 28, 28, 28)
    layout.setSpacing(14)
    button = QPushButton("اعتبارسنجی و تبدیل")
    button.setObjectName("probePrimary")
    button.setMinimumWidth(310)
    button.setMinimumHeight(43)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    box = QCheckBox("اطلاعات مالی را بررسی کرده‌ام و تأیید می‌کنم.")
    box.setObjectName("probeApproval")
    box.setMinimumHeight(52)
    box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    surface = QFrame()
    surface.setObjectName("probeSurface")
    surface.setMinimumHeight(46)
    surface.setFrameShape(QFrame.Shape.StyledPanel)
    surface.setAutoFillBackground(True)
    surface_layout = QHBoxLayout(surface)
    surface_layout.addWidget(QLabel("سطح معناییِ نمونه"))
    layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
    layout.addWidget(box)
    layout.addWidget(surface)
    layout.addStretch()
    if method == "palette":
        p = QPalette(surface.palette())
        p.setColor(QPalette.ColorRole.Window, QColor(TOKENS[theme]["surface"]))
        p.setColor(QPalette.ColorRole.Base, QColor(TOKENS[theme]["surface"]))
        surface.setPalette(p)
    for kind, widget in (("button", button), ("checkbox_unchecked", box),
                         ("surface", surface)):
        apply_method(widget, kind, method, theme, check_asset)
    host.show()
    host.raise_()
    host.activateWindow()
    QTest.qWait(70)
    return host, button, box, surface


def normalize(host, widget, checked=None):
    widget.setEnabled(True)
    widget.setDown(False)
    widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    if checked is not None:
        widget.setChecked(checked)
    host.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.mouseMove(host, QPoint(5, 5))
    QCoreApplication.processEvents()
    QTest.qWait(35)


def render_state(host, widget, state, checked=None):
    normalize(host, widget, checked)
    method = "normal"
    focus_verified = None
    if state == "hover":
        if isinstance(widget, QCheckBox):
            option = QStyleOptionButton()
            option.initFrom(widget)
            indicator = widget.style().subElementRect(
                QStyle.SubElement.SE_CheckBoxIndicator, option, widget)
            QTest.mouseMove(widget, indicator.center())
        else:
            QTest.mouseMove(widget, QPoint(widget.width() // 2, widget.height() // 2))
        method = "QTest.mouseMove"
    elif state == "focus":
        host.activateWindow()
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        focus_verified = bool(widget.hasFocus())
        method = "setFocus(TabFocusReason) + hasFocus"
    elif state == "pressed":
        widget.setDown(True)
        method = "setDown(True)"
    elif state == "disabled":
        widget.setEnabled(False)
        method = "setEnabled(False)"
    QCoreApplication.processEvents()
    QTest.qWait(45)
    image = widget.grab()
    if image.isNull():
        raise RuntimeError("Qt grab produced a null image")
    return image, method, focus_verified


def ensure_hover(host, widget, baseline, checked):
    snap, mode, focus = render_state(host, widget, "hover", checked)
    if difference(snap, baseline)["changed"]:
        return snap, mode, focus
    # Deliberate simulation fallback, never confuse it with a real pointer.
    widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    QCoreApplication.processEvents()
    QTest.qWait(55)
    fallback = widget.grab()
    if difference(fallback, baseline)["changed"]:
        return fallback, "WA_UnderMouse (simulated fallback)", focus
    return snap, "QTest.mouseMove + fallback ineffective", focus


def collect(theme, style_name, method, output, app, check_asset, captures, records):
    host, button, box, surface = make_host(theme, method, check_asset)
    try:
        for kind in WIDGETS:
            widget = button if kind == "button" else box
            checked = None if kind == "button" else (kind == "checkbox_checked")
            normal, normal_method, _ = render_state(host, widget, "normal", checked)
            frames = {"normal": (normal, normal_method, None)}
            for state in STATES[1:]:
                frames[state] = (ensure_hover(host, widget, normal, checked)
                                 if state == "hover" else
                                 render_state(host, widget, state, checked))
            for state, (shot, mode, focus_verified) in frames.items():
                filename = f"{theme}_{style_name}_{method}_{kind}_{state}.png"
                if not shot.save(str(output / filename)):
                    raise RuntimeError(f"Failed saving {filename}")
                result = sample(widget, kind, shot, theme, state)
                pixel_diff = ({"changed": True, "count": None, "fraction": None}
                              if state == "normal" else difference(shot, normal))
                record = dict(theme=theme, style=style_name, method=method,
                              widget=kind, state=state, filename=filename,
                              capture="widget.grab()", state_method=mode,
                              focus_verified=focus_verified,
                              diff_pixels=pixel_diff["count"],
                              diff_fraction=pixel_diff["fraction"],
                              rendered=pixel_diff["changed"], **result)
                records.append(record)
                captures[(theme, style_name, method, kind, state)] = shot
        normalize(host, button)
        surfshot = surface.grab()
        name = f"{theme}_{style_name}_{method}_surface_normal.png"
        if not surfshot.save(str(output / name)):
            raise RuntimeError(f"Failed saving {name}")
        captures[(theme, style_name, method, "surface", "normal")] = surfshot
        img = surfshot.toImage()
        s = px(img, 12, img.height() // 2)
        records.append(dict(theme=theme, style=style_name, method=method,
                            widget="surface", state="normal", filename=name,
                            capture="widget.grab()", state_method="normal",
                            focus_verified=None, rendered=True, diff_pixels=None,
                            diff_fraction=None, bg=s, bg_hex=hex_rgb(s),
                            text=None, text_hex="", target=rgb(TOKENS[theme]["surface"]),
                            target_hex=TOKENS[theme]["surface"].upper(),
                            distance=distance(s, rgb(TOKENS[theme]["surface"])),
                            contrast=None, physical_size=[img.width(), img.height()],
                            dpr=surfshot.devicePixelRatio()))
    finally:
        host.close()
        QCoreApplication.processEvents()


def wrong_selector_control(app, theme, output):
    # Same widget before/after a deliberately non-matching *local* selector.
    host, button, box, surface = make_host(theme, "default", "")
    try:
        normal, _, _ = render_state(host, button, "normal")
        button.setStyleSheet("QPushButton#anObjectNameThatDoesNotExist { background-color: #00FF00; }")
        QCoreApplication.processEvents()
        QTest.qWait(45)
        wrong = button.grab()
        normal.save(str(output / f"{theme}_wrong_selector_before.png"))
        wrong.save(str(output / f"{theme}_wrong_selector_after.png"))
        return difference(normal, wrong)
    finally:
        host.close()


def write_sheet(theme, output, captures, results, styles):
    # Rows: style x method; columns: states; each cell stacks button and both
    # checkbox variants. Missing configurations get explicit text, not fake data.
    tile_w, tile_h, label_h = 370, 226, 28
    left, top = 180, 70
    sheet = QImage(left + 5 * tile_w, top + 9 * tile_h,
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor("#F4F6FA"))
    painter = QPainter(sheet)
    painter.setPen(QColor("#162538"))
    painter.setFont(QFont("Arial", 11))
    painter.drawText(12, 27, f"Qt styling probe / {theme} / NOT a physical-screen capture")
    for col, state in enumerate(STATES):
        painter.drawText(left + col * tile_w + 8, 57, state.upper())
    rows = [(style, method) for style in ("windows11", "windowsvista", "fusion")
            for method in METHODS]
    for ri, (style, method) in enumerate(rows):
        y = top + ri * tile_h
        painter.drawText(8, y + 23, f"{style} / {method}")
        for col, state in enumerate(STATES):
            x = left + col * tile_w
            painter.setPen(QColor("#D4DAE1"))
            painter.drawRect(x, y, tile_w - 4, tile_h - 4)
            for ki, kind in enumerate(WIDGETS):
                image = captures.get((theme, style, method, kind, state))
                if image is None:
                    painter.setPen(QColor("#873A37"))
                    painter.drawText(x + 10, y + 47 + ki * 62, "STYLE NOT AVAILABLE")
                    continue
                target = QRectLike(x + 6, y + 9 + ki * 65, tile_w - 18, 53)
                painter.drawPixmap(target[0], target[1], target[2], target[3], image)
                rec = results.get((theme, style, method, kind, state))
                if rec is not None and rec["classification"] == "NOT_RENDERED":
                    painter.setPen(QColor("#A12E25"))
                    painter.drawText(x + 10, y + 65 + ki * 65, "NOT_RENDERED")
            painter.setPen(QColor("#162538"))
    painter.end()
    path = output / f"contact_sheet_{theme}.png"
    if not sheet.save(str(path)):
        raise RuntimeError(f"Cannot save {path}")


def QRectLike(x, y, w, h):
    # Keep actual source pixels: the contact sheet is a *visual index* only.
    return (x, y, w, h)


def classify(rows):
    defaults = {(r["theme"], r["style"], r["widget"], r["state"]): r
                for r in rows if r["method"] == "default"}
    for r in rows:
        key = (r["theme"], r["style"], r["widget"], r["state"])
        default = defaults.get(key)
        r["default_bg_distance"] = (distance(r["bg"], default["bg"])
                                    if default else None)
        if r["state"] != "normal" and not r["rendered"]:
            status = "NOT_RENDERED"
        elif r["method"] == "default":
            status = "IGNORED"   # Baseline: no customization applied.
        elif r["target"] and r["distance"] is not None and r["distance"] <= 12:
            status = "APPLIED"
        elif r["default_bg_distance"] is not None and r["default_bg_distance"] <= 12:
            status = "IGNORED"
        else:
            status = "PARTIAL"
        r["classification"] = status
        r["hover_change"] = ""
        r["focus_visible"] = ""
        r["pressed_feedback"] = ""
        r["native_shape_preserved"] = (
            "NO (QSS replaces widget painting)" if r["method"] == "qss" else
            "YES (no widget QSS; inferred from mechanism)")
    keys = {(r["theme"], r["style"], r["method"], r["widget"]): {}
            for r in rows if r["widget"] != "surface"}
    for r in rows:
        k = (r["theme"], r["style"], r["method"], r["widget"])
        if k in keys:
            keys[k][r["state"]] = r
    for state_map in keys.values():
        hover = state_map["hover"]["rendered"]
        focus = state_map["focus"]["rendered"] and state_map["focus"]["focus_verified"] is True
        pressed = state_map["pressed"]["rendered"]
        for r in state_map.values():
            r["hover_change"] = "YES" if hover else "NO"
            r["focus_visible"] = "YES" if focus else "NO"
            r["pressed_feedback"] = "YES" if pressed else "NO"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale-tag", default="native")
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    families = {f.casefold(): f for f in QFontDatabase.families()}
    family = families.get("vazirmatn") or families.get("tahoma") or app.font().family()
    app.setFont(QFont(family, 11))
    effective_font = QFontInfo(app.font()).family()
    available = QStyleFactory.keys()
    metadata = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    os_name=platform.platform(), os_version=platform.version(),
                    os_release=platform.release(), windows_build=sys.getwindowsversion().build
                    if sys.platform == "win32" else None,
                    runner_name=os.getenv("RUNNER_NAME"), runner_image=os.getenv("ImageOS"),
                    github_run_id=os.getenv("GITHUB_RUN_ID"),
                    github_sha=os.getenv("GITHUB_SHA"),
                    qt_version=qVersion(), pyside_version=PYSIDE_VERSION,
                    qpa=os.getenv("QT_QPA_PLATFORM", "default"),
                    qt_scale_factor=os.getenv("QT_SCALE_FACTOR"),
                    scale_tag=args.scale_tag, available_styles=available,
                    effective_font=effective_font, requested_point_size=11,
                    device_dpr=app.primaryScreen().devicePixelRatio(),
                    requested_styles=["windows11", "windowsvista", "Fusion"],
                    style_creation={}, color_schemes={}, palette_role_overrides={
                        "widget_palette_active_inactive": ROLE_NAMES,
                        "widget_palette_disabled": ROLE_NAMES,
                        "theme_baseline_app_roles": ["Window", "Base", "WindowText", "Text"],
                        "note": "App palette establishes identical background/text baseline for all methods; no app QSS. Widget palette applies only to palette method."
                    }, captures={}, negative_controls={},
                    remarks=["Qt Widgets are captured through widget.grab() on a runner, not a physical Windows display.",
                             "QPalette colors are requests, not evidence of painted colors.",
                             "State renders require both state intervention and visible pixel differences.",
                             "Font family is QFontInfo application resolution, not per-glyph fallback proof.",
                             "Native shape is mechanism-based inference; visual fidelity requires image review."])
    captures, rows = {}, []
    style_keys = {s.casefold(): s for s in available}
    for theme in ("light", "dark"):
        scheme_detail = {"requested": theme, "mechanism": "UNAVAILABLE"}
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "setColorScheme"):
            try:
                hints.setColorScheme(Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light)
                QCoreApplication.processEvents()
                scheme_detail = {"requested": theme, "mechanism": "QStyleHints.setColorScheme",
                                 "observed": str(hints.colorScheme())}
            except Exception as exc:
                scheme_detail = {"requested": theme, "mechanism": "FAILED", "error": repr(exc)}
        metadata["color_schemes"][theme] = scheme_detail
        for requested in ("windows11", "windowsvista", "Fusion"):
            style_key = style_keys.get(requested.casefold())
            if not style_key:
                metadata["style_creation"][theme + "/" + requested] = "UNAVAILABLE"
                continue
            style = QStyleFactory.create(style_key)
            if style is None:
                metadata["style_creation"][theme + "/" + requested] = "CREATE_FAILED"
                continue
            app.setStyle(style)
            base_palette(app, theme)
            QCoreApplication.processEvents()
            key = requested.casefold()
            metadata["style_creation"][theme + "/" + requested] = {
                "result": "CREATED", "effective": app.style().objectName()}
            asset = make_check_asset(output, theme)
            for method in METHODS:
                collect(theme, key, method, output, app, asset, captures, rows)
            if key == "fusion":
                metadata["negative_controls"][theme + "/wrong_selector"] = (
                    wrong_selector_control(app, theme, output))
    classify(rows)
    # Discriminating negative control: at least one customized Fusion button
    # must actually differ from its default rendering in each tested theme.
    for theme in ("light", "dark"):
        baseline = captures.get((theme, "fusion", "default", "button", "normal"))
        customized = [captures.get((theme, "fusion", m, "button", "normal"))
                      for m in ("palette", "qss")]
        if baseline is None:
            metadata["negative_controls"][theme + "/fusion_distinguishable"] = "UNAVAILABLE"
        else:
            metadata["negative_controls"][theme + "/fusion_distinguishable"] = any(
                image is not None and difference(baseline, image)["changed"]
                for image in customized)
    metadata["captures"] = {
        r["filename"]: {"method": r["state_method"], "grab": r["capture"],
                        "dpr": r["dpr"], "rendered": r["rendered"],
                        "classification": r["classification"],
                        "focus_verified": r["focus_verified"]}
        for r in rows
    }
    fields = ["theme", "style", "method", "widget", "state", "filename", "capture",
              "state_method", "focus_verified", "rendered", "diff_pixels",
              "diff_fraction", "classification", "bg_hex", "text_hex",
              "target_hex", "distance", "default_bg_distance", "contrast",
              "dpr", "physical_size", "hover_change", "focus_visible",
              "pressed_feedback", "native_shape_preserved"]
    with (output / "measurements.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({field: r.get(field) for field in fields})
    result_index = {(r["theme"], r["style"], r["method"], r["widget"], r["state"]): r
                    for r in rows}
    for theme in ("light", "dark"):
        write_sheet(theme, output, captures, result_index, available)
    (output / "environment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PROBE_ARTIFACT_DIR:", output)
    print("STYLE_AVAILABILITY:", json.dumps(metadata["style_creation"]))
    print("NEGATIVE_CONTROLS:", json.dumps(metadata["negative_controls"]))
    print("CAPTURED_IMAGES:", len([r for r in rows if r["filename"].endswith(".png")]))
    failures = [key for key, value in metadata["negative_controls"].items()
                if value is False or (isinstance(value, dict) and value["changed"])]
    if failures:
        raise SystemExit("Negative control failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
