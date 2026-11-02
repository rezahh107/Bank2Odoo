"""Independent post-capture audit of Stage 3 evidence before publication.

Uses saved JSON and original PNG headers; no PySide6/GUI simulation required.
Fail closed if output is incomplete, mixed with stale captures, or misattributed.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

from tests.qt_stage3_geometry_classifier import (
    SCHEMES, VARIANTS, WIDTHS, classify_geometry, expected_states,
)

MAIN_SHA = "e0f50ab8605024896bf6975050fb4034b874514e"
PR20_SHA = "aa4362adfa8cd3e6e2873c8b36de79ce8183e3bd"


def png_dimensions(path: Path):
    with path.open("rb") as f:
        header = f.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise AssertionError(f"Not an original PNG: {path}")
    return list(struct.unpack(">II", header[16:24]))


def validate(folder: Path, *, head: str):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("qualification_test_head") != head:
        raise AssertionError("Stale/mixed source Head")
    if manifest.get("source_heads") != {"main": MAIN_SHA, "journal_free_pr20": PR20_SHA}:
        raise AssertionError("Pinned source identities changed")
    if manifest.get("machine", {}).get("qpa") != "windows":
        raise AssertionError("Not a native Windows QPA run")
    font = manifest.get("font", {})
    if font.get("family") != "Vazirmatn" or font.get("version") != "v33.003":
        raise AssertionError("Canonical font not proven")
    matrix = [(v, s, w) for v in VARIANTS for s in SCHEMES for w in WIDTHS]
    cases = manifest.get("cases", [])
    if [(c["variant"], c["scheme"], c["width"]) for c in cases] != matrix:
        raise AssertionError("Missing/duplicate/out-of-order candidate matrix")
    image_files = set()
    n_states = n_controls = n_pass = 0
    md = (folder / "MEASUREMENTS.md").read_text(encoding="utf-8")
    for case in cases:
        variant, width = case["variant"], case["width"]
        states = case["states"]
        if [state["state"] for state in states] != list(expected_states(width)):
            raise AssertionError("Missing or substituted required state")
        actual = classify_geometry(states, variant=variant, width=width)
        if actual != case.get("geometry_classification"):
            raise AssertionError("Stored verdict disagrees with independent reclassification")
        if actual["status"] == "GEOMETRY_PASS":
            n_pass += 1
        expected_md = f"| {variant} | {case['scheme']} | {width} |"
        rows = [line for line in md.splitlines() if line.startswith(expected_md)]
        if len(rows) != 1 or not rows[0].endswith("| " + actual["status"] + " |"):
            raise AssertionError("Markdown and manifest verdict disagree")
        for state in states:
            n_states += 1
            n_controls += len(state["required_controls"])
            for shot in state["screenshots"]:
                name = shot["file"]
                if "/" in name or "\\" in name or name in image_files:
                    raise AssertionError("Unsafe or duplicate screenshot name")
                image_files.add(name)
                image_size = png_dimensions(folder / name)
                if image_size != shot["png_px"]:
                    raise AssertionError("PNG file dimensions disagree with metadata")
                expected = [round(x * shot["qt_dpr"]) for x in state["widget"]]
                if image_size != expected:
                    raise AssertionError("Not original-resolution QWidget.grab")
    negative = manifest.get("negative")
    if not isinstance(negative, dict):
        raise AssertionError("Missing negative evidence")
    neg_verdict = classify_geometry([negative], variant="journal_free", width=500)
    if negative.get("geometry_classification") != neg_verdict or neg_verdict["status"] != "NOT_QUALIFIED":
        raise AssertionError("Negative control must remain NOT_QUALIFIED")
    if negative.get("horizontal_overflow_logical_px", 0) <= 0:
        raise AssertionError("500px negative stopped demonstrating clipping")
    for shot in negative["screenshots"]:
        name = shot["file"]
        image_files.add(name)
        if png_dimensions(folder / name) != shot["png_px"]:
            raise AssertionError("Negative PNG dimensions invalid")
    expected_sheets = ["contact_" + variant + "_" + scheme + ".png"
                       for variant in VARIANTS for scheme in SCHEMES]
    if manifest.get("contact_sheets") != expected_sheets:
        raise AssertionError("Contact-sheet matrix not preserved")
    for name in expected_sheets:
        image_files.add(name)
        if png_dimensions(folder / name) != [1375, 675]:
            raise AssertionError("Contact sheet is missing or malformed")
    actual_pngs = {p.name for p in folder.glob("*.png")}
    if actual_pngs != image_files:
        raise AssertionError(f"Stale/unreferenced/missing PNG: {sorted(actual_pngs ^ image_files)}")
    narrative = (folder / "STAGE3_DECISION_FA.md").read_text(encoding="utf-8")
    if head not in narrative or "NOT_PROVEN" not in narrative:
        raise AssertionError("Stale interpretation or unqualified acceptance claim")
    if f"Geometry qualified: {n_pass}/{len(cases)}" not in narrative:
        raise AssertionError("Interpretation outcome does not match manifest")
    return {"head": head, "cases": len(cases), "states": n_states,
            "visible_control_measurements": n_controls,
            "geometry_pass": n_pass, "negative": neg_verdict["status"],
            "png": len(image_files)}


def main():
    folder = Path(os.environ["STAGE3_EVIDENCE"]).resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    print("STAGE3_EVIDENCE_AUDIT " + json.dumps(validate(folder, head=head)), flush=True)


if __name__ == "__main__":
    main()
