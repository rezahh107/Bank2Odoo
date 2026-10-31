"""Test-only discriminator: saved-path QLabel sizing versus reveal/scroll (fictional data)."""
from __future__ import annotations
import argparse, csv, json, os, platform, sys, tempfile
from pathlib import Path
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QPoint, Qt, QEventLoop, QTimer, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication
from bank2odoo.ui.window import MainWindow, configure_application

def fixture(path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Fictional test data — not a bank statement"])
        w.writerow(["ردیف","تاریخ","زمان","شماره سریال","شرح",
                    "مبلغ گردش بدهکار","مبلغ گردش بستانکار","مانده","واریز کننده/ذینفع"])
        w.writerow(["1","1405/07/01","10:00","A1","واریز ساختگی","0","100","100"])
        w.writerow(["2","1405/07/02","11:00","A2","کارمزد ساختگی","25","0",""])

def wait_finished(w, signal, app):
    if w._thread is None: return
    loop=QEventLoop(); timer=QTimer(); timer.setSingleShot(True)
    timer.timeout.connect(loop.quit); signal.connect(loop.quit)
    timer.start(20000); loop.exec()
    if not timer.isActive(): raise RuntimeError("Worker timed out")
    timer.stop()
    for _ in range(100):
        app.processEvents()
        if w._thread is None: return
    raise RuntimeError("Worker did not join")

def measure(w, app, case, output):
    for _ in range(8): app.processEvents()
    viewport=w.scroll.viewport(); body=w.scroll.widget()
    def rect(widget):
        p=widget.mapTo(viewport, QPoint(0,0))
        return [p.x(),p.y(),widget.width(),widget.height()]
    def size(s): return [s.width(),s.height()]
    h=w.scroll.horizontalScrollBar(); v=w.scroll.verticalScrollBar()
    x={"case":case, "window":size(w.size()), "viewport":size(viewport.size()),
       "content":size(body.size()),"body_min_hint":size(body.minimumSizeHint()),
       "hscroll":{"minimum":h.minimum(),"maximum":h.maximum(),"value":h.value()},
       "vscroll":{"minimum":v.minimum(),"maximum":v.maximum(),"value":v.value()},
       "layout":w._workspace.direction().name,"breakpoint":w._workspace_breakpoint,
       "saved_label_min_hint":size(w.saved_paths.minimumSizeHint()),
       "saved_label_hint":size(w.saved_paths.sizeHint()),
       "saved_label_rect":rect(w.saved_paths),
       "result_rect":rect(w._result_column),"input_rect":rect(w._input_column),
       "action_rect":rect(w.convert_button),"state_rect":rect(w.result_state),
       "saved":w._saved, "source_file_fictional":True}
    pm=w.grab(); name=case+".png"
    if pm.isNull() or not pm.save(str(output/name),"PNG"):
        raise RuntimeError("PNG grab failed: "+name)
    x["image"]=name; x["image_actual"]=size(pm.size()); x["dpr"]=pm.devicePixelRatio()
    return x

def run_case(app, output, theme, width, height):
    with tempfile.TemporaryDirectory(prefix="B2O_FICTIONAL_") as tmp:
        folder=Path(tmp)/("مسیر_ساختگی_"*6)
        folder.mkdir()
        source=folder/("FAKE_IRR_ISO_"+"a"*52+".csv")
        fixture(source)
        out=folder/"private_output";out.mkdir()
        w=MainWindow()
        try:
            w.resize(width,height);w.show();app.processEvents()
            w.set_source(source);wait_finished(w,w.detection_done,app)
            if w.source is None:raise AssertionError("fictional source detection failed")
            w.source_unit.setCurrentIndex(w.source_unit.findData("IRR"))
            w.target_unit.setCurrentIndex(w.target_unit.findData("IRR"))
            w.journal.setText("ژورنال فرضی");w.approved.setChecked(True)
            w.start_conversion();wait_finished(w,w.conversion_done,app)
            if w.result is None:raise AssertionError("fictional conversion failed")
            w.output_directory.setText(str(out));w.save_files()
            wait_finished(w,w.save_done,app)
            if not w._saved or "دو فایل ایجاد شدند" not in w.saved_paths.text():
                raise AssertionError("actual fictional paired-save failed")
            long_text=w.saved_paths.text()
            results=[]
            prefix=f"{theme}_{width}x{height}_"
            def snap(label, reveal=False, bottom=False):
                if bottom:
                    w.scroll.verticalScrollBar().setValue(w.scroll.verticalScrollBar().maximum())
                if reveal:w._reveal_result()
                results.append(measure(w,app,prefix+label,output))
            w.scroll.horizontalScrollBar().setValue(0)
            snap("long_before");snap("long_after",reveal=True)
            snap("long_vertical_bottom",bottom=True)
            # Change only visible QLabel text, not save result or file paths.
            w.saved_paths.setText("دو فایل ایجاد شدند؛ مسیرها فقط در آزمون ساختگی‌اند.")
            for _ in range(8):app.processEvents()
            w.scroll.horizontalScrollBar().setValue(0)
            snap("short_before");snap("short_after",reveal=True)
            w.saved_paths.setText(long_text)
            for _ in range(8):app.processEvents()
            w.scroll.horizontalScrollBar().setValue(0)
            snap("long_restored_after",reveal=True)
            return results
        finally:
            w.close();app.processEvents()

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True,type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    data=[]
    for theme in ("light","dark"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if theme=="light" else Qt.ColorScheme.Dark)
        app.processEvents();configure_application(app)
        for size in ((940,830),(650,520),(600,480)):
            data.extend(run_case(app,args.output,theme,*size))
    payload={"environment":{"platform":platform.platform(),"python":sys.version,
             "qpa":app.platformName(),"qt":qVersion(),"pyside6":pyside_version,
             "effective_style_final":app.style().objectName(),
             "font":QFontInfo(app.font()).family(),"scale_factor":os.environ.get("QT_SCALE_FACTOR"),
             "physical_windows11_verified":False,"actual_os_scheme_verified":False},
             "cases":data,"source":"actual Qt Widgets, fictional statement and real paired-save only"}
    (args.output/"measurements.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    for x in data:
        print(x["case"],"H",x["hscroll"],"content",x["content"],"viewport",x["viewport"],
              "labelMin",x["saved_label_min_hint"],"columns",x["input_rect"],x["result_rect"])
    print("QUALIFIED_CASES",len(data))
if __name__=="__main__":main()
