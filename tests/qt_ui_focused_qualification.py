"""Review-only real-product Qt geometry and checkbox paint qualification.

Never modifies the financial engine, data, Odoo integration, or production UI.
Captures native QWidget pixels on a Windows GitHub-hosted runner using fictional CSV.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import weakref
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, qVersion
from PySide6.QtGui import QFontInfo, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QStyle, QStyleFactory, QStyleOptionButton

from bank2odoo.ui import window as product
from tests.qt_theme_pilot_capture import fixture, wait_finished

BASELINE = "5d4b950c29a73433c043a53dc266cee9192d3de4"
SIZES = ((940, 830), (650, 520), (600, 480))
SCHEMES = ("light", "dark")
# Each treatment is an in-memory diagnostic on the actual product widget.
B_TREATMENTS = ("baseline", "unscoped_rule", "bright_border", "negative")


def luminance(rgb):
    parts = []
    for c in rgb:
        x = c / 255
        parts.append(x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4)
    return .2126 * parts[0] + .7152 * parts[1] + .0722 * parts[2]


def contrast(a, b):
    aa, bb = sorted((luminance(a), luminance(b)), reverse=True)
    return round((aa + .05) / (bb + .05), 3)


def rgb_at(image, x, y):
    x = max(0, min(image.width() - 1, round(x)))
    y = max(0, min(image.height() - 1, round(y)))
    c = image.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def hexcolor(rgb):
    return "#%02X%02X%02X" % rgb


def render_probe(cb):
    opt = QStyleOptionButton()
    opt.initFrom(cb)
    sty = cb.style()
    r = sty.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, cb)
    # Composited window pixels include the actual adjacent painted surface.
    host = cb.window()
    pm = host.grab()
    image = pm.toImage()
    dpr = pm.devicePixelRatio()
    origin = cb.mapTo(host,QPoint(0,0))
    def pixel(x, y):
        return rgb_at(image, (origin.x()+x)*dpr, (origin.y()+y)*dpr)
    outside = []
    for y in (r.top()-7, r.top()-5, r.bottom()+5, r.bottom()+7):
        if 2 <= y < cb.height()-2:
            outside.extend(pixel(r.center().x()+dx,y) for dx in (-3,0,3))
    if not outside:
        outside = [pixel(r.center().x(),cb.height()-3)]
    bg = Counter(outside).most_common(1)[0][0]
    border = []
    for x in range(r.left(), r.right()+1):
        for y in (r.top()+1, r.top()+2, r.bottom()-1, r.bottom()-2):
            if 0 <= x < cb.width() and 0 <= y < cb.height():
                border.append(pixel(x,y))
    for y in range(r.top()+3, r.bottom()-2):
        for x in (r.left()+1, r.left()+2, r.right()-1, r.right()-2):
            if 0 <= x < cb.width() and 0 <= y < cb.height():
                border.append(pixel(x,y))
    ratios = sorted(contrast(c,bg) for c in border)
    colors = Counter(border).most_common(8)
    return {
        "style_class":type(sty).__name__, "style_object_name":sty.objectName(),
        "metric_width":sty.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth,opt,cb),
        "metric_height":sty.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight,opt,cb),
        "indicator_rect":[r.x(),r.y(),r.width(),r.height()],
        "grab_size_px":[image.width(),image.height()], "grab_dpr":dpr,
        "background_rgb":hexcolor(bg),
        "background_sampling":"COMPOSITED window; center x +/-3; 5/7 logical px above/below indicator; RGB mode of up to 12 samples",
        "border_sampling":"inside the indicator, 1/2 logical pixels from four edges, DPR-scaled nearest-point",
        "border_color_histogram":[{"rgb":hexcolor(c),"n":n} for c,n in colors],
        "border_p95_ratio":ratios[int(.95*(len(ratios)-1))] if ratios else None,
        "border_max_ratio":max(ratios) if ratios else None,
        "border_fraction_ge_3":round(sum(x>=3 for x in ratios)/len(ratios),4) if ratios else 0,
        "samples":len(ratios), "qss":cb.styleSheet(),
        "app_qss":QApplication.instance().styleSheet(),
        "parent_qss":cb.parentWidget().styleSheet(),
        "palette_window":cb.palette().color(QPalette.ColorRole.Window).name(),
        "palette_base":cb.palette().color(QPalette.ColorRole.Base).name(),
        "palette_text":cb.palette().color(QPalette.ColorRole.Text).name()
    }


def geometry(w):
    w._workspace.activate()
    w.scroll.widget().layout().activate()
    a,b = w._input_column,w._result_column
    viewport = w.scroll.viewport()
    def box(widget):
        point = widget.mapTo(viewport,QPoint(0,0))
        return [point.x(),point.y(),widget.width(),widget.height()]
    aa,bb=box(a),box(b)
    horiz = w._workspace.direction() in (
        QBoxLayout.Direction.RightToLeft,QBoxLayout.Direction.LeftToRight)
    return {
        "layout_direction":w._workspace.direction().name,
        "main_widget_direction":w.layoutDirection().name,
        "body_widget_direction":w.scroll.widget().layoutDirection().name,
        "input_widget_direction":a.layoutDirection().name,
        "result_widget_direction":b.layoutDirection().name,
        "input_rect_viewport":aa,"result_rect_viewport":bb,
        "input_right_of_result":aa[0]+aa[2]/2 > bb[0]+bb[2]/2,
        "input_above_result":aa[1]+aa[3]/2 < bb[1]+bb[3]/2,
        "is_horizontal":horiz,
        "expected_order_present":(
            (aa[0]+aa[2]/2 > bb[0]+bb[2]/2) if horiz
            else (aa[1]+aa[3]/2 < bb[1]+bb[3]/2)),
        "horizontal_scroll_max":w.scroll.horizontalScrollBar().maximum(),
        "vertical_scroll_max":w.scroll.verticalScrollBar().maximum(),
        "window_wh":[w.width(),w.height()],
        "viewport_wh":[viewport.width(),viewport.height()],
        "breakpoint":w._workspace_breakpoint,
        "focus_chain_names":focus_chain(w)
    }


def focus_chain(w):
    out=[]
    current=w.select_button
    seen=set()
    for _ in range(100):
        if id(current) in seen:break
        seen.add(id(current))
        if current.focusPolicy()!=Qt.FocusPolicy.NoFocus and current.isVisibleTo(w):
            out.append({"class":type(current).__name__,"object":current.objectName(),
                        "accessible":current.accessibleName() or current.toolTip(),
                        "label":current.text()[:60] if hasattr(current,"text") else ""})
        current=current.nextInFocusChain()
    return out[:40]


def shot(w, root, name, metadata):
    w.scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    pm=w.grab()
    file=name+".png"
    if pm.isNull() or not pm.save(str(root/file),"PNG"):
        raise RuntimeError("Could not save original-resolution screenshot "+file)
    metadata["screenshots"].append({
        "file":file,"physical_px":[pm.width(),pm.height()],
        "device_pixel_ratio":pm.devicePixelRatio(),"geometry":geometry(w),
        "approved":w.approved.isChecked(),"selected_digest":w._selected_digest is not None,
        "approved_digest_matches":w._approved_digest is not None and w._approved_digest==w._selected_digest,
        "converted":w.result is not None,"saved":w._saved,
        "save_enabled":w.save_button.isEnabled()
    })


def application_scheme(app, scheme):
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if scheme=="dark" else Qt.ColorScheme.Light)
    app.processEvents()
    product.configure_application(app)
    app.processEvents()


def apply_layout_variant(w, variant):
    if variant=="baseline":return
    if variant!="horizontal_ltr":raise ValueError(variant)
    # Do not capture a bound method here: window -> closure -> window would
    # survive until interpreter shutdown, after native Qt style teardown.
    original=product.MainWindow._reflow_workspace
    weak_window=weakref.ref(w)
    def reflow():
        current=weak_window()
        if current is None:
            return
        original(current)
        if current._workspace.direction()==QBoxLayout.Direction.RightToLeft:
            current._workspace.setDirection(QBoxLayout.Direction.LeftToRight)
            current._workspace.invalidate()
            current.scroll.widget().layout().activate()
    w._reflow_workspace=reflow
    reflow()


def treatment(w, kind):
    cb=w.approved
    if kind=="baseline":return
    if kind=="no_proxy":
        cb.setStyle(QStyleFactory.create("Fusion"))
    elif kind=="unscoped_rule":
        cb.setStyleSheet(cb.styleSheet().replace(
            "QCheckBox#financialApproval::indicator", "QCheckBox::indicator"))
    elif kind=="bright_border":
        cb.setStyleSheet(cb.styleSheet().replace("#DCE7F0","#FF00FF"))
    elif kind=="negative":
        cb.setStyleSheet("QCheckBox#financialApproval::indicator:unchecked {"
            "border: 2px solid #161B22; background-color: #151A21; }")
    else:
        raise ValueError(kind)
    QApplication.processEvents()


def interactions(w, app):
    cb=w.approved
    # Source digest has been established, financial context supplied.
    before=render_probe(cb)
    cb.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    QTest.keyClick(cb,Qt.Key_Space)
    keyboard_checked=cb.isChecked() and w._approved_digest==w._selected_digest
    QTest.keyClick(cb,Qt.Key_Space)
    keyboard_unchecked=not cb.isChecked() and w._approved_digest is None
    # 5px is deliberately away from the RTL checkbox glyph and its text.
    QTest.mouseClick(cb,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,
                     QPoint(5,cb.height()//2))
    row_checked=cb.isChecked() and w._approved_digest==w._selected_digest
    w.journal.setText(w.journal.text()+"-changed")
    invalidated=(not cb.isChecked() and w._approved_digest is None and w.result is None)
    return {"unchecked_pixel_probe":before,"space_checks":keyboard_checked,
            "space_unchecks":keyboard_unchecked,"full_row_click":row_checked,
            "context_edit_revokes":invalidated,
            "row_height":cb.height(),"accessible_name":cb.accessibleName(),
            "focus_policy":cb.focusPolicy().name}


def run_case(app, out, scheme, size, family, variant):
    application_scheme(app,scheme)
    print("START",family,variant,scheme,size,flush=True)
    # A product-owned rule value is varied before widget construction.
    # Normal product refresh therefore keeps the diagnostic treatment.
    old_rule=product._APPROVAL_DARK_QSS
    if family=="checkbox":
        if variant=="unscoped_rule":
            product._APPROVAL_DARK_QSS=old_rule.replace(
                "QCheckBox#financialApproval::indicator","QCheckBox::indicator")
        elif variant=="bright_border":
            product._APPROVAL_DARK_QSS=old_rule.replace("#DCE7F0","#FF00FF")
        elif variant=="negative":
            product._APPROVAL_DARK_QSS=(
                "QCheckBox#financialApproval::indicator:unchecked {"
                " border: 2px solid #161B22; background-color: #151A21; }")
    w=product.MainWindow()
    w.resize(*size)
    w.show()
    app.processEvents()
    if family=="rtl": apply_layout_variant(w,variant)
    app.processEvents()
    code=f"{family}_{variant}_{scheme}_{size[0]}x{size[1]}"
    record={
        "id":code,"family":family,"variant":variant,"requested_scheme":scheme,
        "size_requested":list(size),"app_style":app.style().objectName(),
        "qpa":app.platformName(),
        "checkbox_style_class":type(w.approved.style()).__name__,
        "font":QFontInfo(w.approved.font()).family(),
        "font_pt":QFontInfo(w.approved.font()).pointSizeF(),
        "dpr":w.devicePixelRatioF(),
        "effective_scheme":app.styleHints().colorScheme().name,
        "screenshots":[],"error":None
    }
    try:
        shot(w,out,code+"_initial",record)
        with tempfile.TemporaryDirectory(prefix="b2o-qt-qual-") as temp:
            folder=Path(temp)
            sample=folder/"fictional.csv"
            fixture(sample,balanced=True)
            w.set_source(sample)
            wait_finished(w,w.detection_done,app)
            if w.source is None: raise AssertionError("Synthetic source detection failed")
            w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
            w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
            w.journal.setText("ژورنال ساختگی")
            if family=="checkbox":
                record["interaction"]=interactions(w,app)
            w.approved.setChecked(True)
            if w._approved_digest != w._selected_digest:
                raise AssertionError("Source-bound approval not established")
            if family=="checkbox":
                record["checked_indicator"]=render_probe(w.approved)
                shot(w,out,code+"_checked",record)
                w.approved.setFocus(Qt.FocusReason.TabFocusReason)
                app.processEvents()
                shot(w,out,code+"_focus",record)
            w.start_conversion()
            wait_finished(w,w.conversion_done,app)
            if w.result is None or not w.result.balance_status.startswith("PASS"):
                raise AssertionError("Synthetic balanced conversion did not PASS")
            shot(w,out,code+"_result",record)
            destination=folder/"private"
            destination.mkdir()
            w.output_directory.setText(str(destination))
            w.save_files()
            wait_finished(w,w.save_done,app)
            if not w._saved: raise AssertionError("Synthetic paired save failed")
            shot(w,out,code+"_saved",record)
            if not any(destination.iterdir()):
                raise AssertionError("No private synthetic output saved")
    except Exception as exc:
        record["error"]=f"{type(exc).__name__}: {exc}"
    finally:
        w.close()
        app.processEvents()
        product._APPROVAL_DARK_QSS=old_rule
    print("DONE",code,"error",record["error"],flush=True)
    return record


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--family",choices=("rtl","checkbox"))
    parser.add_argument("--variant")
    parser.add_argument("--scheme",choices=SCHEMES)
    parser.add_argument("--width",type=int)
    parser.add_argument("--height",type=int)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)

    if args.worker:
        # Native Qt Windows style/proxy teardown is process-local. A unique
        # QApplication per case prevents one experimental widget from
        # retaining QStyle/native references across unrelated treatments.
        app=QApplication([])
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        rec=run_case(app,args.output,args.scheme,(args.width,args.height),
                     args.family,args.variant)
        (args.output/("case_"+rec["id"]+".json")).write_text(
            json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
        if rec["error"]:
            raise SystemExit(2)
        return

    payload={
        "revision":BASELINE,"collected_utc":datetime.now(timezone.utc).isoformat(),
        "environment":{
            "os":platform.platform(),"python":sys.version,
            "qt":qVersion(),"pyside6":__import__("PySide6").__version__,
            "qpa_from_windows_worker":None,
            "qt_qpa_platform_env":os.getenv("QT_QPA_PLATFORM"),
            "display_scaling_physical_win11_verified":False,
            "color_scheme_test_override":True,
            "native_workstation_verified":False,
            "process_isolation":"one Qt QApplication per spawned Python worker"
        },"cases":[],"limitations":[
            "Synthetic Windows GitHub-hosted runner, not accountant workstation",
            "Qt styleHint Light/Dark override is not measured Windows OS preference",
            "Rasterized pixels are sampled, but no perceptual or screen-reader acceptance",
            "Contrast samples depend on QStyle indicator geometry and local pixel rasterization"
        ]
    }
    tasks=[]
    for scheme in SCHEMES:
        for size in SIZES:
            for variant in ("baseline","horizontal_ltr"):
                tasks.append((scheme,size,"rtl",variant))
        for variant in B_TREATMENTS:
            tasks.append((scheme,SIZES[0],"checkbox",variant))
    for scheme,size,family,variant in tasks:
        cmd=[sys.executable,"-m","tests.qt_ui_focused_qualification",
             "--output",str(args.output),"--worker",
             "--scheme",scheme,"--family",family,"--variant",variant,
             "--width",str(size[0]),"--height",str(size[1])]
        child=subprocess.run(cmd,capture_output=True,text=True,
                             encoding="utf-8",errors="replace",timeout=90)
        print("CASE",family,variant,scheme,size,"exit",child.returncode,flush=True)
        if child.stdout:
            print(child.stdout[-3500:],flush=True)
        if child.stderr:
            print(child.stderr[-3500:],file=sys.stderr,flush=True)
        ident=f"{family}_{variant}_{scheme}_{size[0]}x{size[1]}"
        case_path=args.output/("case_"+ident+".json")
        if case_path.exists():
            rec=json.loads(case_path.read_text(encoding="utf-8"))
        else:
            rec={"id":ident,"family":family,"variant":variant,
                 "error":"Child process did not produce measurements; exit="+str(child.returncode),
                 "screenshots":[]}
        if child.returncode and not rec.get("error"):
            rec["error"]="Worker native/runtime exit code "+str(child.returncode)
        if rec.get("qpa"):
            payload["environment"]["qpa_from_windows_worker"]=rec["qpa"]
        payload["cases"].append(rec)
    (args.output/"measurements.json").write_text(
        json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    summary=["# Real-product Qt UI diagnostic — synthetic Windows QPA",
             "",f"Base: {BASELINE}",
             f"OS: {payload['environment']['os']}; Qt: {qVersion()}; "
             f"QPA: {payload['environment']['qpa_from_windows_worker']}",
             "Theme selection is an application-only test override, not an OS preference measurement.",
             ""]
    for item in payload["cases"]:
        shots=item["screenshots"]
        g=shots[0]["geometry"] if shots else {}
        pixels=item.get("interaction",{}).get("unchecked_pixel_probe",{})
        summary.append(
            f"- {item['id']}: error={item['error'] or 'none'}; "
            f"order_ok={g.get('expected_order_present')}; "
            f"horizontal_scroll={g.get('horizontal_scroll_max')}; "
            f"unchecked_border_p95={pixels.get('border_p95_ratio')}; "
            f"border_fraction_3={pixels.get('border_fraction_ge_3')}")
    summary+=["","No production patch or physical Windows 11 acceptance. See measurements.json and original-resolution PNGs."]
    (args.output/"SUMMARY.md").write_text("\n".join(summary)+"\n",encoding="utf-8")
    print("\n".join(summary),flush=True)
    if any(i["error"] for i in payload["cases"]):
        raise SystemExit("One or more diagnostic workers failed; see measurements.json")


if __name__=="__main__":
    main()
