"""CSV and human-readable private report are written only as a review candidate."""

import csv
from io import StringIO
import json
from pathlib import Path
import tempfile
import os

from bank2odoo.core.engine import Conversion
from bank2odoo.validation.financial import StatementError, exact_sum


def output_csv(result: Conversion) -> str:
    out = StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Date", "Label", "Amount"])
    for row in result.rows:
        writer.writerow((row.date.isoformat(), row.label, format(row.converted, "f")))
    return out.getvalue()


def control_report(result: Conversion) -> str:
    debit_count = sum(m.signed < 0 for m in result.rows)
    credit_count = len(result.rows) - debit_count
    lines = [
        "# Bank2Odoo — PRIVATE accountant control report",
        "STATUS: REVIEW CANDIDATE ONLY — NOT authorized for live Odoo import",
        "No Odoo connection, journal validation, duplicate-import check, or accountant approval performed.",
        f"Source filename: {result.filename}",
        f"SHA-256 exact source bytes: {result.sha256}",
        f"Bank: {result.bank}; Source format: {result.encoding}; Separator: {result.separator}",
        f"Journal (user-entered, UNVERIFIED): {result.journal}",
        f"Source unit: {result.source_unit}; target unit: {result.target_unit}; approved factor: {result.factor}",
        f"Period (observed rows): {min(m.date for m in result.rows)} .. {max(m.date for m in result.rows)}",
        f"Source rows: {len(result.rows)}; debit rows: {debit_count}; credit rows: {credit_count}",
        f"Debit total ({result.source_unit}): {result.debit_total}; credit total: {result.credit_total}; net: {result.net}",
        f"Converted net ({result.target_unit}): {exact_sum(m.converted for m in result.rows)}",
        f"Source row order: {result.ordering}; Output order: unchanged source order",
        f"Balance check: {result.balance_status}",
        "Inferred opening/closing (source units; not independently attested): " +
        f"{result.opening if result.opening is not None else 'NOT_PROVEN'} / " +
        f"{result.closing if result.closing is not None else 'NOT_PROVEN'}",
        "## Exceptions, possible duplicates, tentative associations",
        *(["- " + issue for issue in result.issues] or ["- No row-level flags; independent financial acceptance still outstanding"]),
        "## Accountant decisions still required",
        "- Confirm file identity, reporting period, source and destination units, decimal precision and Bank Journal/account.",
        "- Confirm bank balance endpoints and validity of inferred opening, including completeness of selected period.",
        "- Check existing Odoo Bank Transactions/manual entries for overlapping movements before any import.",
        "- Verify fees, reversals, corrections and any tentative transaction association against receipts.",
        "- Separately authorize Odoo import/reconciliation; this report never authorizes them.",
        "## Source-to-destination trace (JSON objects, one per output row; private)",
    ]
    for i, m in enumerate(result.rows, start=2):
        trace = {"csv_row": i, "source_physical_row": m.row.physical_row,
                 "sheet": m.row.sheet, "source_report_row": m.row.fields.get("report_row", ""),
                 "source_jalali_date": m.row.fields["date"], "source_time": m.row.fields.get("time", ""),
                 "gregorian_date": m.date.isoformat(), "reference": m.reference,
                 "transaction_type": m.kind, "source_signed": str(m.signed),
                 "source_balance": str(m.balance) if m.balance is not None else None,
                 "dest_amount": format(m.converted, "f"), "dest_label": m.label,
                 "original_columns": m.row.original}
        lines.append(json.dumps(trace, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


def save_candidate(result: Conversion, csv_path: Path, report_path: Path) -> None:
    """Prevent a partially failed run from leaving an apparently complete CSV."""
    csv_path, report_path = csv_path.resolve(), report_path.resolve()
    if csv_path == report_path or csv_path.exists() or report_path.exists():
        raise StatementError("Output files must be distinct and must not already exist")
    if csv_path.parent != report_path.parent or not csv_path.parent.is_dir():
        raise StatementError("Both outputs must use the same existing private directory")
    # Git ignores are not sufficient to keep real bank data out of a public
    # checkout, especially for plain-text control reports.
    checkout = Path(__file__).resolve().parents[2]
    if csv_path.is_relative_to(checkout) or report_path.is_relative_to(checkout):
        raise StatementError("Financial outputs must be saved outside the public source checkout")
    # Publish the private report first: an interrupted run must never leave
    # an unaccompanied Odoo-looking CSV behind.
    files = (report_path, csv_path)
    contents = (control_report(result), output_csv(result))
    staged = []
    published = []
    try:
        for content in contents:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=csv_path.parent,
                                             prefix=".bank2odoo-", suffix=".tmp", delete=False) as handle:
                staged.append(Path(handle.name))
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for temporary, destination in zip(staged, files):
            if destination.exists():
                raise StatementError(f"Output appeared during conversion: {destination.name}")
            # os.link refuses to overwrite existing destination on both POSIX/Windows.
            os.link(temporary, destination)
            published.append(destination)
    except Exception:
        for destination in published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
