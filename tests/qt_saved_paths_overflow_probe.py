"""Test-only discriminator: saved-path QLabel sizing versus reveal/scroll (fictional data)."""
from __future__ import annotations
import argparse, csv, json, os, platform, subprocess, sys, tempfile
from pathlib import Path
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QPoint, QRect, Qt, QEventLoop, QTimer, qVersion
from PySide6.QtGui import QColor, QFontInfo, QImage, QPainter
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
       "saved":w._saved, "source_file_fictional":True,
       "columns_minimum_size_hint":{
            "input":size(w._input_column.minimumSizeHint()),
            "result":size(w._result_column.minimumSizeHint())},
       "group_boxes":{
            box.title():{"minimum":size(box.minimumSizeHint()), "preferred":size(box.sizeHint()),"rect":rect(box)}
            for box in w.findChildren(__import__("PySide6.QtWidgets",fromlist=["QGroupBox"]).QGroupBox)
       },
       "widget_min_hints":{
            "source_picker":size(w.select_button.minimumSizeHint()),
            "path":size(w.path_field.minimumSizeHint()),
            "journal":size(w.journal.minimumSizeHint()),
            "source_unit":size(w.source_unit.minimumSizeHint()),
            "approval":size(w.approved.minimumSizeHint()),
            "primary_action":size(w.convert_button.minimumSizeHint()),
            "directory_button":size(w.directory_button.minimumSizeHint()),
            "output_path":size(w.output_directory.minimumSizeHint())}}
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
            saved_text=w.saved_paths.text()
            results=[]
            prefix=f"{theme}_{width}x{height}_"
            def snap(label, reveal=False, bottom=False):
                if bottom:
                    w.scroll.verticalScrollBar().setValue(w.scroll.verticalScrollBar().maximum())
                if reveal:w._reveal_result()
                results.append(measure(w,app,prefix+label,output))
            # Production baseline before/after focus and normal vertical scroll.
            w.scroll.horizontalScrollBar().setValue(0)
            snap("production_before");snap("production_after",reveal=True)
            snap("production_vertical_bottom",bottom=True)
            if hasattr(w,"saved_csv_path"):
                paths=list(out.glob("Bank2Odoo_*"))
                csv_path=next(x for x in paths if x.suffix==".csv")
                report_path=next(x for x in paths if x.suffix==".txt")
                if (w.saved_csv_path.text()!=str(csv_path)
                    or w.saved_report_path.text()!=str(report_path)):
                    raise AssertionError("Full output paths not exposed exactly")
                for x in results[-3:]:
                    if x["hscroll"]["maximum"] != 0:
                        raise AssertionError("Fixed product retains horizontal overflow: "+x["case"])
                # Test-only deliberate return of the *legacy* long QLabel,
                # keeping all other widgets and saved values unchanged.
                from bank2odoo.ui.window import latin
                long_text=("دو فایل ایجاد شدند:\\nCSV: "+latin(csv_path)
                           +"\\nگزارش کنترل خصوصی: "+latin(report_path))
                w.saved_paths.setText(long_text)
                for _ in range(8):app.processEvents()
                w.scroll.horizontalScrollBar().setValue(0)
                snap("legacy_long_injected_before")
                snap("legacy_long_injected_after",reveal=True)
                w.saved_paths.setText(saved_text)
                for _ in range(8):app.processEvents()
                w.scroll.horizontalScrollBar().setValue(0)
                snap("production_restored_after",reveal=True)
                if results[-1]["hscroll"]["maximum"] != 0:
                    raise AssertionError("Fixed product did not restore narrow width")
            else:
                w.saved_paths.setText("دو فایل ایجاد شدند؛ مسیرها فقط در آزمون ساختگی‌اند.")
                for _ in range(8):app.processEvents()
                w.scroll.horizontalScrollBar().setValue(0)
                snap("short_before");snap("short_after",reveal=True)
                w.saved_paths.setText(saved_text)
                for _ in range(8):app.processEvents()
                w.scroll.horizontalScrollBar().setValue(0)
                snap("long_restored_after",reveal=True)
            return results
        finally:
            w.close();app.processEvents()

def make_contact_sheets(output):
    """Small diagnostic contact sheets; original PNGs remain untouched."""
    for theme in ("light", "dark"):
        sheet = QImage(1040, 1240, QImage.Format.Format_ARGB32)
        sheet.fill(QColor("#f4f5f7"))
        painter = QPainter(sheet)
        try:
            for row, size in enumerate(("940x830", "650x520", "600x480")):
                for col, phase in enumerate(("production_after", "legacy_long_injected_after")):
                    name = f"{theme}_{size}_{phase}.png"
                    picture = QImage(str(output / name))
                    if picture.isNull():
                        raise RuntimeError("Missing Qt screenshot " + name)
                    target_width, target_height = 485, 352
                    scaled = picture.scaled(target_width, target_height,
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                    x = 18 + col * 520 + (target_width-scaled.width()) // 2
                    y = 28 + row * 400
                    painter.setPen(QColor("#252525"))
                    painter.drawText(QRect(x, y, 480, 24),
                                     Qt.AlignmentFlag.AlignLeft,
                                     f"{size}: " + ("PRODUCTION" if col == 0 else "LEGACY INJECTED"))
                    painter.drawImage(x, y + 28, scaled)
        finally:
            painter.end()
        if not sheet.save(str(output / ("contact_" + theme + ".png")), "PNG"):
            raise RuntimeError("Cannot save Qt contact sheet")

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
             "checkout_head":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
             "effective_style_final":app.style().objectName(),
             "font":QFontInfo(app.font()).family(),"scale_factor":os.environ.get("QT_SCALE_FACTOR"),
             "physical_windows11_verified":False,"actual_os_scheme_verified":False},
             "cases":data,"source":"actual Qt Widgets, fictional statement and real paired-save only"}
    (args.output/"measurements.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    make_contact_sheets(args.output)
    for x in data:
        print(x["case"],"H",x["hscroll"],"content",x["content"],"viewport",x["viewport"],
              "labelMin",x["saved_label_min_hint"],"groups",[v["minimum"][0] for v in x["group_boxes"].values()],"columns",x["input_rect"],x["result_rect"])
    print("QUALIFIED_CASES",len(data))
if __name__=="__main__":main()
