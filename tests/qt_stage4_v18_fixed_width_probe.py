"""Evidence-only Stage 4 Bank2Odoo fixed-width qualification on hosted Windows Qt.
Compares current main shell under an instance-only two-column override. Does NOT
implement the v18 browser design, change production code, save outputs, or import Odoo.
Synthetic statement input is created in a private TemporaryDirectory.
"""
from __future__ import annotations
import json, os, platform, subprocess, tempfile
from pathlib import Path
from threading import Event
from unittest.mock import patch
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint, Qt, QEventLoop, QTimer, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QBoxLayout
from bank2odoo.ui import window as ui
from tests.qt_theme_pilot_capture import fixture, wait_finished
from adapters.qt_style_probe.font_runtime import initialize_font, assert_widget_font

REF = "ccec758c92b65469403533d946b69d3035c09779"
CANDIDATES = (900, 940)
STATES = ("initial", "detected", "approval", "busy", "cancel_requested", "cancel_completed", "not_proven", "save_error_simulation", "saved_simulation", "pass")
CONTROLS = ("select_button","path_field","detected","source_unit",
            "target_unit","precision","factor","approved","convert_button","status")
RESULT_CONTROLS = ("result_state","summary","directory_button","output_directory","saved_paths")
SAVED_CONTROLS = ("saved_csv_path","saved_report_path")
OUTPUT = Path(os.environ.get("STAGE4_OUTPUT","stage4-output"))
OUTPUT.mkdir(parents=True,exist_ok=True)

def settle(app,w):
    for _ in range(12):
        app.processEvents()
        w._workspace.activate()
        w.scroll.widget().layout().activate()

def force_two_columns(w):
    def fixed():
        if w._workspace.direction()!=QBoxLayout.Direction.LeftToRight:
            w._workspace.setDirection(QBoxLayout.Direction.LeftToRight)
            w._workspace.invalidate()
    w._reflow_workspace = fixed
    fixed()

def fit_control(app,w,control):
    vp = w.scroll.viewport()
    bar = w.scroll.verticalScrollBar()
    if not control.isVisibleTo(w):
        return {"visible":False,"reachable":False}
    before=bar.value()
    # Use actual scrollbar movements, not ensureWidgetVisible's programmatic promise.
    current=control.mapTo(vp,QPoint(0,0))
    content_y=current.y()+bar.value()
    chosen=max(0,min(bar.maximum(), content_y+control.height()-vp.height()))
    options=(0,chosen,bar.maximum())
    measures=[]
    for pos in options:
        bar.setValue(pos)
        app.processEvents()
        p=control.mapTo(vp,QPoint(0,0))
        h=(p.x()>=0 and p.x()+control.width()<=vp.width())
        v=(p.y()>=0 and p.y()+control.height()<=vp.height())
        measures.append({"scroll":pos,"rect":[p.x(),p.y(),control.width(),control.height()],
                         "horizontal":h,"vertical":v,"contained":h and v})
    bar.setValue(before)
    app.processEvents()
    return {"visible":True,"reachable":any(m["contained"] for m in measures),
            "positions":measures}

def capture(app,w,tag,position):
    vbar=w.scroll.verticalScrollBar()
    vbar.setValue(position)
    settle(app,w)
    pm=w.grab()
    if pm.isNull():raise RuntimeError("Null QWidget grab")
    name=tag+".png"
    if not pm.save(str(OUTPUT/name),"PNG"):raise RuntimeError("PNG save failed")
    return {"file":name,"width_px":pm.width(),"height_px":pm.height(),
            "dpr":pm.devicePixelRatio(),"vertical_scroll":vbar.value()}

def measure(app,w,scheme,width,state):
    settle(app,w)
    vp=w.scroll.viewport()
    content=w.scroll.widget()
    required=CONTROLS+(RESULT_CONTROLS if state in ("not_proven","save_error_simulation","saved_simulation") else ())+(
        SAVED_CONTROLS if state=="saved_simulation" else ())
    checks={key:fit_control(app,w,getattr(w,key)) for key in required}
    missing=[k for k,v in checks.items() if not v["visible"] or not v["reachable"]]
    row={
        "scheme":scheme,"candidate_width":width,"state":state,
        "window":[w.width(),w.height()],"minimum":[w.minimumWidth(),w.minimumHeight()],
        "viewport":[vp.width(),vp.height()],"content":[content.width(),content.height()],
        "scroll_max":[w.scroll.horizontalScrollBar().maximum(),w.scroll.verticalScrollBar().maximum()],
        "horizontal_overflow_px":max(0, content.width()-vp.width()),
        "workspace":w._workspace.direction().name,
        "required_controls":list(required),"failed_reachability":missing,
        "effective_style":app.style().objectName(),
        "effective_font":QFontInfo(w.font()).family(),
        "approval_checked":w.approved.isChecked(),
        "approval_source_bound":bool(w._selected_digest and w._approved_digest==w._selected_digest),
        "result_present":w.result is not None,
        "save_outcome_is_simulated":state in ("save_error_simulation","saved_simulation"),
    }
    hfail=row["horizontal_overflow_px"]>0 or row["scroll_max"][0]>0
    row["geometry_verdict"]="GEOMETRY_FAIL" if missing or hfail or w.width()!=width else "GEOMETRY_PASS"
    name=f"{scheme}_{width}_{state}"
    shots=[capture(app,w,name+"_top",0)]
    if state in ("not_proven","save_error_simulation","saved_simulation"):
        shots.append(capture(app,w,name+"_bottom",w.scroll.verticalScrollBar().maximum()))
    row["screenshots"]=shots
    return row


def keyboard_approval_check(app,w):
    # Physical Tab keys via QTest. This is Qt-hosted keyboard simulation, not
    # proof of an accountant navigating a real keyboard.
    w.select_button.setFocus(Qt.TabFocusReason)
    app.processEvents()
    trail=[]
    found=False
    for _ in range(32):
        focused=app.focusWidget()
        trail.append(type(focused).__name__ if focused is not None else "NONE")
        if focused is w.approved:
            found=True
            break
        QTest.keyClick(focused or w,Qt.Key_Tab)
        app.processEvents()
    if not found:
        raise AssertionError("Financial approval absent from Tab traversal")
    # Toggle real native checkbox by Space; preserve digest-bound semantics.
    QTest.keyClick(w.approved,Qt.Key_Space)
    app.processEvents()
    if w.approved.isChecked() or w._approved_digest is not None:
        raise AssertionError("Space failed to revoke financial approval")
    QTest.keyClick(w.approved,Qt.Key_Space)
    app.processEvents()
    if not (w.approved.isChecked() and w._approved_digest==w._selected_digest):
        raise AssertionError("Space did not bind financial approval")
    return {"found_approval_in_tab_path":True,"number_of_tabs":len(trail)-1,
            "space_revocation_and_reapproval":True}

def negative_control(app):
    # Deliberately too narrow. Demonstrates that the measurement can FAIL,
    # rather than returning PASS regardless of geometry.
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    ui.configure_application(app)
    w=ui.MainWindow()
    w.setMinimumSize(500,480)
    force_two_columns(w)
    w.resize(500,650)
    w.show()
    settle(app,w)
    w.resize(500,650)
    settle(app,w)
    try:
        result=measure(app,w,"light_negative",500,"initial")
        if result["geometry_verdict"]!="GEOMETRY_FAIL":
            raise AssertionError("Negative fixture did not expose insufficient width")
        return result
    finally:
        w.close()
        settle(app,w)

def run_one(app,scheme,width,source):
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if scheme=="simulated_dark"
                                     else Qt.ColorScheme.Light)
    ui.configure_application(app)
    assert_widget_font(app)
    w=ui.MainWindow()
    w.setMinimumSize(width,480)
    force_two_columns(w)
    w.resize(width,650)
    w.show()
    settle(app,w)
    w.resize(width,650)
    settle(app,w)
    try:
        out=[measure(app,w,scheme,width,"initial")]
        w.set_source(source)
        wait_finished(w,w.detection_done,app)
        if w.source is None:raise AssertionError("synthetic source detection failed")
        out.append(measure(app,w,scheme,width,"detected"))
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.approved.setChecked(True)
        if not (w.approved.isChecked() and w._approved_digest==w._selected_digest):
            raise AssertionError("source SHA approval did not bind")
        out.append(measure(app,w,scheme,width,"approval"))
        keyboard=keyboard_approval_check(app,w)
        out[-1]["keyboard"]=keyboard
        entered,release=Event(),Event()
        actual_convert=ui.convert
        def controlled_convert(path,context):
            entered.set()
            if not release.wait(12):
                raise RuntimeError("Synthetic conversion hold timed out")
            return actual_convert(path,context)
        with patch.object(ui,"convert",side_effect=controlled_convert):
            try:
                w.start_conversion()
                if not entered.wait(10):
                    raise AssertionError("Synthetic busy state not reached")
                out.append(measure(app,w,scheme,width,"busy"))
                w.cancel_conversion()
                out.append(measure(app,w,scheme,width,"cancel_requested"))
            finally:
                release.set()
            wait_finished(w,w.conversion_done,app)
        if w.result is not None:raise AssertionError("Cancelled operation produced a result")
        out.append(measure(app,w,scheme,width,"cancel_completed"))
        w.start_conversion()
        wait_finished(w,w.conversion_done,app)
        if w.result is None or not w.result.balance_status.startswith("NOT_PROVEN"):
            raise AssertionError("Expected synthetic NOT_PROVEN result")
        out.append(measure(app,w,scheme,width,"not_proven"))
        # Presentation-only save states; never call save_candidate or write CSV.
        w.saved_paths.setText("ذخیره کامل نشد؛ برای تلاش دوباره پوشه خصوصی را انتخاب کنید.")
        w._set_message("خطای ذخیره: مسیر خصوصی قابل استفاده نبود.")
        out.append(measure(app,w,scheme,width,"save_error_simulation"))
        w._saved=True
        w.saved_paths.setText("دو مسیر خروجی ساختگی — هیچ فایلی ایجاد نشده است")
        w.saved_csv_path.setText("C:/synthetic/private/output_candidate_very_long_name.csv")
        w.saved_report_path.setText("C:/synthetic/private/control_report_very_long_name.txt")
        w.saved_path_fields.show()
        w._sync_actions()
        out.append(measure(app,w,scheme,width,"saved_simulation"))
        balanced=Path(source.parent)/("synthetic_balanced_"+scheme+"_"+str(width)+".csv")
        fixture(balanced,balanced=True)
        w.set_source(balanced)
        wait_finished(w,w.detection_done,app)
        w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
        w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
        w.approved.setChecked(True)
        w.start_conversion()
        wait_finished(w,w.conversion_done,app)
        if w.result is None or not w.result.balance_status.startswith("PASS"):
            raise AssertionError("Expected synthetic PASS result")
        out.append(measure(app,w,scheme,width,"pass"))
        return out
    finally:
        w.close()
        settle(app,w)

def main():
    if platform.system()!="Windows":
        raise SystemExit("NOT_RUN: requires actual hosted Windows Qt QPA")
    rev=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    app=QApplication([])
    info=initialize_font(app,11)
    screen=app.primaryScreen()
    metadata={
        "target_git_head":rev,"expected_base":REF,
        "v18_is_html_reference_only":True,
        "host":platform.platform(),"python":platform.python_version(),
        "pyside_qt":qVersion(),"qpa":app.platformName(),
        "font":info,"screen_geometry":screen.geometry().getRect(),
        "screen_available":screen.availableGeometry().getRect(),
        "screen_dpr":screen.devicePixelRatio(),
        "screen_logical_dpi":screen.logicalDotsPerInch(),
        "scopes":["current source Qt shell, not v18 implementation",
                  "simulated dark Qt hint, not Windows OS Dark",
                  "hosted Windows CI, not Owner workstation",
                  "simulated save result, not real file publication"],
    }
    if app.platformName()!="windows":raise AssertionError("Windows QPA required")
    rows=[]
    with tempfile.TemporaryDirectory(prefix="stage4-synthetic-") as t:
        f=Path(t)/"synthetic_mellat_test.csv"
        fixture(f,balanced=False)
        for scheme in ("light","simulated_dark"):
            for width in CANDIDATES:
                rows.extend(run_one(app,scheme,width,f))
    negative=negative_control(app)
    bad=[x for x in rows if x["geometry_verdict"]!="GEOMETRY_PASS"]
    result={"metadata":metadata,"cases":rows,"negative_control":negative,"total":len(rows),"geometry_fail_count":len(bad),
            "decision":"NOT_PROVEN: geometry alone cannot approve minimum width or v18 appearance"}
    (OUTPUT/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("STAGE4_SUMMARY "+json.dumps({"head":rev,"total":len(rows),"failures":len(bad),
         "work_area":metadata["screen_available"],"qpa":metadata["qpa"],"negative":negative["geometry_verdict"]},ensure_ascii=False))
    for row in rows:
        print("STAGE4_CASE "+json.dumps({k:row[k] for k in ("scheme","candidate_width","state",
            "geometry_verdict","horizontal_overflow_px","failed_reachability")},ensure_ascii=False))
    # Both fail and pass scenarios remain evidence; nonzero when there is a confirmed failure.
    if bad:raise AssertionError("Stage4 candidate geometry failed; see manifest")

if __name__=="__main__":
    main()
