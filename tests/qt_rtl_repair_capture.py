"""Production RTL ordering acceptance captures on actual Windows Qt QPA.

Each child process owns a single QApplication and actual MainWindow. Original
BASE source is imported from git, not visually imitated or patched. Synthetic
financial operations reuse the repository's full-product capture harness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, qVersion
from PySide6.QtGui import QFontInfo, QImage, QPainter
from PySide6.QtWidgets import QApplication, QBoxLayout

from bank2odoo.ui import window as repaired_ui
from tests import qt_theme_pilot_capture as pilot

BASE = "5d4b950c29a73433c043a53dc266cee9192d3de4"
SIZES = ((940, 830), (650, 520), (600, 480))
SCHEMES = ("light", "dark")
CAPTURE_VIEWS = {
    "initial": "top",
    "validation_error": "top",
    "cancel_requested": "action",
    "not_proven_result": "action",
    "ready_to_save_no_folder": "action",
    "folder_selected": "action",
    "save_failure": "action",
    "saved_success": "bottom",
    "pass_result": "action",
}
FOCUS = ("select_button", "source_unit", "target_unit", "journal",
         "approved", "convert_button", "directory_button")


def import_baseline(target: Path):
    content = subprocess.check_output(
        ["git", "show", f"{BASE}:bank2odoo/ui/window.py"])
    path = target / "baseline_window.py"
    path.write_bytes(content)
    spec = importlib.util.spec_from_file_location("bank2odoo_rtl_original", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load pinned baseline UI")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def focus_chain(w):
    seen = set()
    controls = []
    current = w.select_button
    for _ in range(120):
        if id(current) in seen:
            break
        seen.add(id(current))
        controls.append(current)
        current = current.nextInFocusChain()
    indices = {name: controls.index(getattr(w, name)) if getattr(w, name) in controls
               else -1 for name in FOCUS}
    if any(indices[name] < 0 for name in FOCUS):
        raise AssertionError("Missing focus control: " + str(indices))
    if list(indices.values()) != sorted(indices.values()):
        raise AssertionError("Task focus order not in source-to-save sequence: "+str(indices))
    names = {name: getattr(w, name).accessibleName() for name in FOCUS}
    if not all(names[x] for x in
               ("source_unit", "target_unit", "journal", "approved")):
        raise AssertionError("Required financial control accessible name lost")
    return {"indices": indices, "accessible_names": names}


def geometry(w):
    w._workspace.activate()
    w.scroll.widget().layout().activate()
    view=w.scroll.viewport()
    def rect(widget):
        p=widget.mapTo(view,QPoint(0,0))
        return [p.x(),p.y(),widget.width(),widget.height()]
    a,b=rect(w._input_column),rect(w._result_column)
    direction=w._workspace.direction()
    is_horizontal=direction in (QBoxLayout.Direction.RightToLeft,
                                QBoxLayout.Direction.LeftToRight)
    right=a[0]+a[2]/2 > b[0]+b[2]/2
    top=a[1]+a[3]/2 < b[1]+b[3]/2
    if is_horizontal:
        if min(a[0],b[0]) < 0 or max(a[0]+a[2],b[0]+b[2])>view.width()+2:
            raise AssertionError("A workspace column clipped horizontally")
    else:
        if min(a[0],b[0]) < 0 or max(a[0]+a[2],b[0]+b[2])>view.width()+2:
            raise AssertionError("Narrow columns clipped horizontally")
    if w.scroll.horizontalScrollBar().maximum()!=0:
        raise AssertionError("Horizontal viewport scrollbar appeared")
    return {
        "requested_breakpoint":w._workspace_breakpoint,
        "direction":direction.name,"main_layout_direction":w.layoutDirection().name,
        "input_rect_viewport":a,"result_rect_viewport":b,
        "input_right_of_result":right,"input_above_result":top,
        "horizontal":is_horizontal,"horizontal_scroll_max":0,
        "vertical_scroll_max":w.scroll.verticalScrollBar().maximum(),
        "actual_window_wh":[w.width(),w.height()],
        "actual_viewport_wh":[view.width(),view.height()],
        "focus":focus_chain(w)
    }


def capture(w, root, label, records, phase):
    state=next((key for key in CAPTURE_VIEWS if label.endswith("_"+key)), None)
    if state is None:
        return
    app=QApplication.instance()
    location=CAPTURE_VIEWS[state]
    if location=="top":
        w.scroll.verticalScrollBar().setValue(0)
    elif location=="bottom":
        w.scroll.verticalScrollBar().setValue(
            w.scroll.verticalScrollBar().maximum())
    else:
        if hasattr(w,"_reveal_result"):
            w._reveal_result()
        else:
            w.scroll.ensureWidgetVisible(w.convert_button)
            w.scroll.ensureWidgetVisible(w.result_state)
    app.processEvents()
    dims=geometry(w)
    requested_w=int(label.split("_")[2].split("x")[0])
    wide=requested_w==940
    if wide:
        if not dims["horizontal"]:
            raise AssertionError("940-wide must be horizontal in pinned Windows QPA")
        # Original baseline deliberately fails the new product ordering
        # expectation: this is our independent negative control.
        if dims["input_right_of_result"] != (phase=="after"):
            raise AssertionError("RTL repaired/original discriminator failed")
    else:
        if dims["horizontal"] or not dims["input_above_result"]:
            raise AssertionError("Narrow stages lost natural vertical order")
    pm=w.grab()
    name=label+".png"
    if pm.isNull() or not pm.save(str(root/name),"PNG"):
        raise RuntimeError("Cannot save original-resolution screenshot "+name)
    if pm.devicePixelRatio()!=w.devicePixelRatioF():
        raise AssertionError("DPR mismatch")
    records.append({
        "file":name,"state":state,"view":location,
        "requested_window_wh":list(map(int,label.split("_")[2].split("x"))),
        "physical_png_wh":[pm.width(),pm.height()],
        "dpr":pm.devicePixelRatio(),
        "geometry":dims,
        "source_sha_present":w._selected_digest is not None,
        "approval_digest_matches":(
            w._approved_digest is not None and
            w._approved_digest==w._selected_digest),
        "result_status":w.result.balance_status if w.result else None,
        "saved":w._saved,"save_enabled":w.save_button.isEnabled(),
        "file_path_is_long":len(w.path_field.text())>110,
        "saved_csv_path_len":len(w.saved_csv_path.text()),
        "saved_report_path_len":len(w.saved_report_path.text())
    })


def worker(args):
    app=QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    phase=args.phase
    with tempfile.TemporaryDirectory() as tmp:
        private=Path(tmp)
        longdir=private/("نمونه_ساختگی_"*4+"LTR_IRR_1405")
        longdir.mkdir()
        source=longdir/("fictional_"+"X"*42+".csv")
        pilot.fixture(source)
        mod=import_baseline(private) if phase=="before" else repaired_ui
        case_id=f"{phase}_{args.scheme}_{args.width}x{args.height}"
        rows=[]
        original=pilot.snapshot
        def scoped_snapshot(app,w,out,label,unused):
            capture(w,out,label,rows,phase)
        pilot.snapshot=scoped_snapshot
        try:
            pilot.take(app,mod,phase,args.scheme,args.width,args.height,
                       args.output,source,[])
        finally:
            pilot.snapshot=original
        expected=set(CAPTURE_VIEWS)
        got={r["state"] for r in rows}
        if got!=expected:
            raise AssertionError(f"Missing capture states: {sorted(expected-got)}")
        matching={r["state"]:r for r in rows}
        if not matching["saved_success"]["saved"]:
            raise AssertionError("Real paired synthetic save not recorded")
        if matching["saved_success"]["saved_csv_path_len"]<110:
            raise AssertionError("Mixed Persian/LTR long saved paths not exercised")
        if not matching["not_proven_result"]["result_status"].startswith("NOT_PROVEN"):
            raise AssertionError("NOT_PROVEN became an unsupported PASS")
        if not matching["pass_result"]["result_status"].startswith("PASS"):
            raise AssertionError("Synthetic balanced case no longer passes")
        result={
            "id":case_id,"phase":phase,"scheme":args.scheme,
            "qpa":app.platformName(),"qt":qVersion(),
            "pyside6":__import__("PySide6").__version__,
            "style":app.style().objectName(),"font":QFontInfo(app.font()).family(),
            "font_pt":QFontInfo(app.font()).pointSizeF(),
            "DPR":app.devicePixelRatio() if hasattr(app,"devicePixelRatio") else 1,
            "records":rows,
            "source_is_exact_baseline":phase=="before",
            "synthetic_held_worker_cancellation_exercised":True,
            "synthetic_paired_save_failure_recovery_exercised":True
        }
        (args.output/(case_id+".json")).write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print("CAPTURED",case_id,len(rows),"states",flush=True)


def contact(out, before, after, scheme, width, height, state):
    parts=[]
    for phase in ("before","after"):
        path=out/f"{phase}_{scheme}_{width}x{height}_{state}.png"
        img=QImage(str(path))
        if img.isNull():
            raise AssertionError("Missing original PNG "+str(path))
        parts.append(img)
    # A compact *derivative* review sheet; original PNGs remain separately
    # available, never rescaled or substituted for measurement.
    cellw=520
    scaled=[x.scaledToWidth(cellw, Qt.TransformationMode.SmoothTransformation)
            for x in parts]
    maxh=max(x.height() for x in scaled)
    sheet=QImage(cellw*2+24,maxh+58,QImage.Format.Format_ARGB32)
    sheet.fill(Qt.GlobalColor.white)
    painter=QPainter(sheet)
    try:
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(10,20,"BEFORE: pinned main")
        painter.drawText(cellw+16,20,"AFTER: RTL repair")
        painter.drawImage(8,35,scaled[0])
        painter.drawImage(cellw+16,35,scaled[1])
    finally:
        painter.end()
    name=f"compare_{scheme}_{width}x{height}_{state}.png"
    if not sheet.save(str(out/name),"PNG"):
        raise AssertionError("Cannot save comparison "+name)
    return name


def parent(args):
    out=args.output
    cases=[]
    for scheme in SCHEMES:
        for width,height in SIZES:
            for phase in ("before","after"):
                cmd=[sys.executable,"-m","tests.qt_rtl_repair_capture",
                     "--worker","--output",str(out),
                     "--phase",phase,"--scheme",scheme,
                     "--width",str(width),"--height",str(height)]
                job=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",
                                   errors="replace",timeout=110)
                name=f"{phase}_{scheme}_{width}x{height}"
                print(name,"exit",job.returncode,job.stdout[-1200:],flush=True)
                if job.stderr: print(job.stderr[-2500:],file=sys.stderr,flush=True)
                if job.returncode:
                    raise RuntimeError(f"Native Windows capture failed: {name}, exit {job.returncode}")
                cases.append(json.loads((out/(name+".json")).read_text(encoding="utf-8")))
    for idx in range(0,len(cases),2):
        before,after=cases[idx:idx+2]
        if before["scheme"]!=after["scheme"]:
            raise AssertionError("Mismatched test schemes")
        for state in CAPTURE_VIEWS:
            b=next(x for x in before["records"] if x["state"]==state)
            a=next(x for x in after["records"] if x["state"]==state)
            if b["geometry"]["focus"]!=a["geometry"]["focus"]:
                raise AssertionError("Changed tab/focus/accessibility contract "+state)
            if b["geometry"]["actual_window_wh"]!=a["geometry"]["actual_window_wh"]:
                raise AssertionError("Changed window dimensions "+state)
            if b["geometry"]["horizontal_scroll_max"]!=a["geometry"]["horizontal_scroll_max"]:
                raise AssertionError("Unexpected horizontal scroll change "+state)
    app=QApplication([])
    sheets=[]
    for scheme in SCHEMES:
        for w,h in SIZES:
            for state in ("initial","not_proven_result","saved_success"):
                sheets.append(contact(out,"before","after",scheme,w,h,state))
    metadata={
        "production_baseline":BASE,
        "feature_checkout_head":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "os":platform.platform(),"python":sys.version,"qt":qVersion(),
        "qpa":cases[0]["qpa"],"scheme_source":"QStyleHints test override",
        "physical_windows11_acceptance":False,
        "physical_scaling_100_125_150":"NOT_TESTED",
        "accountant_comprehension":"NOT_TESTED",
        "assistive_technology":"NOT_TESTED",
        "cases":cases,"contact_sheets":sheets
    }
    (out/"measurements.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),
                                         encoding="utf-8")
    (out/"SUMMARY.md").write_text(
        "# Production RTL workspace repair — synthetic native Windows Qt evidence\n\n"
        f"Baseline \`{BASE}\`, feature \`{metadata['feature_checkout_head']}\`.\n\n"
        f"Cases {len(cases)} (before/after × Light/Dark × 3 sizes), "
        f"original-resolution PNGs {len(list(out.glob('*_*.png')))-len(sheets)}, "
        f"compact contact sheets {len(sheets)}.\n\n"
        "Full synthetic workflow executed: validation error, keyboard/source-bound "
        "approval, held-worker cancellation, NOT_PROVEN, PASS, failed save, "
        "successful paired private save with long Persian/LTR paths.\n\n"
        "Negative control: exact unchanged original Windows widget order detected "
        "as reversed at 940px; corrected layout detected as intended; narrow stacked.\n\n"
        "No production dark-checkbox styling changes, no real accountant workstation, "
        "no actual physical DPI 100/125/150, no screen-reader acceptance.\n",
        encoding="utf-8"
    )
    print("RTL EVIDENCE SUCCESS",len(cases),len(sheets),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--phase",choices=("before","after"))
    parser.add_argument("--scheme",choices=SCHEMES)
    parser.add_argument("--width",type=int)
    parser.add_argument("--height",type=int)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.worker:
        worker(args)
    else:
        parent(args)


if __name__=="__main__":
    main()
