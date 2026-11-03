"""Evidence-only Stage 4 Bank2Odoo fixed-width qualification on hosted Windows Qt.
Compares current main shell under an instance-only two-column override. Does NOT
implement the v18 browser design, change production code, save outputs, or import Odoo.
Synthetic statement input is created in a private TemporaryDirectory.
"""
from __future__ import annotations
import json, os, platform, subprocess, tempfile
from pathlib import Path
from PySide6.QtCore import QPoint, Qt, QEventLoop, QTimer, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QBoxLayout
from bank2odoo.ui import window as ui
from tests.qt_theme_pilot_capture import fixture, wait_finished
from adapters.qt_style_probe.font_runtime import initialize_font, assert_widget_font

REF = "ccec758c92b65469403533d946b69d3035c09779"
CANDIDATES = (900, 940)
STATES = ("initial", "detected", "approval", "not_proven", "save_error_simulation", "saved_simulation")
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
    bad=[x for x in rows if x["geometry_verdict"]!="GEOMETRY_PASS"]
    result={"metadata":metadata,"cases":rows,"total":len(rows),"geometry_fail_count":len(bad),
            "decision":"NOT_PROVEN: geometry alone cannot approve minimum width or v18 appearance"}
    (OUTPUT/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("STAGE4_SUMMARY "+json.dumps({"head":rev,"total":len(rows),"failures":len(bad),
         "work_area":metadata["screen_available"],"qpa":metadata["qpa"]},ensure_ascii=False))
    for row in rows:
        print("STAGE4_CASE "+json.dumps({k:row[k] for k in ("scheme","candidate_width","state",
            "geometry_verdict","horizontal_overflow_px","failed_reachability")},ensure_ascii=False))
    # Both fail and pass scenarios remain evidence; nonzero when there is a confirmed failure.
    if bad:raise AssertionError("Stage4 candidate geometry failed; see manifest")

if __name__=="__main__":
    main()
