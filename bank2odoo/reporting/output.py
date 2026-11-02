"""CSV and human-readable private report are written only as a review candidate."""

import csv
from io import StringIO
import json
from pathlib import Path
import tempfile
import os

from bank2odoo.core.engine import Conversion
from bank2odoo.validation.financial import StatementError, exact_sum
from bank2odoo.version import VERSION


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
        f"Producing application version: Bank2Odoo {VERSION}",
        "STATUS: REVIEW CANDIDATE ONLY — NOT authorized for live Odoo import",
        "Conversion completed for observed movements; balance diagnostics are optional evidence, NOT accounting approval.",
        "No Odoo connection, journal validation, duplicate-import check, or accountant approval performed.",
        f"Source filename: {result.filename}",
        f"SHA-256 exact source bytes: {result.sha256}",
        f"Bank: {result.bank}; Source format: {result.encoding}; Separator: {result.separator}",
        (f"Journal (user-entered, UNVERIFIED): {result.journal}"
         if result.journal and result.journal.strip() else
         "Destination Journal: select the correct Bank Journal separately inside Odoo; NOT verified by Bank2Odoo."),
        f"Source unit: {result.source_unit}; target unit: {result.target_unit}; approved factor: {result.factor}",
        f"Destination decimal precision (applied; Odoo-unverified): {result.decimal_places}",
        f"Period (observed rows): {min(m.date for m in result.rows)} .. {max(m.date for m in result.rows)}",
        f"Source rows: {len(result.rows)}; debit rows: {debit_count}; credit rows: {credit_count}",
        f"Debit total ({result.source_unit}): {result.debit_total}; credit total: {result.credit_total}; net: {result.net}",
        f"Converted net ({result.target_unit}): {exact_sum(m.converted for m in result.rows)}",
        f"Source row order: {result.ordering}; Output order: unchanged source order",
        f"Balance check: {result.balance_status}",  # Preserved for legacy private report readers.
        "Balance diagnostics do not block conversion of otherwise valid observed movements.",
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
                 "source_time_raw": m.row.raw_time, "time_evidence_issue": m.time_issue,
                 "gregorian_date": m.date.isoformat(), "reference": m.reference,
                 "transaction_type": m.kind, "source_signed": str(m.signed),
                 "source_balance": str(m.balance) if m.balance is not None else None,
                 "balance_evidence_issue": m.balance_issue,
                 "dest_amount": format(m.converted, "f"), "dest_label": m.label,
                 "original_columns": m.row.original}
        lines.append(json.dumps(trace, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


class SavePublicationError(OSError):
    """A save failed or cleanup was incomplete; outcome describes observed final files.

    COMPLETE_PAIR means both expected byte-for-byte files exist but cleanup
    failed, not that all filesystem housekeeping succeeded.
    """

    def __init__(self, message: str, *, outcome: str, cleanup_failed: bool) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.cleanup_failed = cleanup_failed


def save_candidate(result: Conversion, csv_path: Path, report_path: Path) -> None:
    """Publish report first, never overwrite, and inspect the final pair after errors.

    Two independent hard links are NOT a crash-atomic multi-file transaction.
    Failures are classified from observed files; unsafe/unknown results fail
    closed and require manual inspection rather than an automatic retry.
    """
    csv_path, report_path = csv_path.resolve(), report_path.resolve()
    if csv_path == report_path or csv_path.exists() or report_path.exists():
        raise StatementError("Output files must be distinct and must not already exist")
    if csv_path.parent != report_path.parent or not csv_path.parent.is_dir():
        raise StatementError("Both outputs must use the same existing private directory")
    checkout = Path(__file__).resolve().parents[2]
    if csv_path.is_relative_to(checkout) or report_path.is_relative_to(checkout):
        raise StatementError("Financial outputs must be saved outside the public source checkout")

    # Order is deliberately report first: a disrupted save must not create a
    # standalone Odoo-looking CSV before its private trace.
    files = (report_path, csv_path)
    contents = (control_report(result), output_csv(result))
    expected = tuple(content.encode("utf-8") for content in contents)
    staged: list[Path] = []
    published: list[Path] = []
    cleanup_failures: list[OSError] = []
    primary: Exception | None = None

    try:
        for content in contents:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=csv_path.parent,
                prefix=".bank2odoo-", suffix=".tmp", delete=False
            ) as handle:
                staged.append(Path(handle.name))
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for temporary, destination in zip(staged, files):
            if destination.exists():
                raise StatementError(f"Output appeared during conversion: {destination.name}")
            # os.link fails rather than replacing a destination on Windows/NTFS
            # and POSIX; do not substitute os.replace or rename.
            os.link(temporary, destination)
            published.append(destination)
        if any(path.read_bytes() != data for path, data in zip(files, expected)):
            raise OSError("Published output pair did not match the staged bytes")
    except Exception as exc:
        primary = exc
        # Never unlink final output paths after publication. A different writer
        # may have replaced a published path before this exception, so path
        # membership in `published` does not prove current file ownership.
        # Keep any partial outputs for explicit manual inspection instead.
    finally:
        for temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                cleanup_failures.append(cleanup_error)

    def observed_outcome() -> str:
        try:
            present = tuple(path.exists() for path in files)
            if any(exists and path not in published for path, exists in zip(files, present)):
                return "AMBIGUOUS"
            if not any(present):
                return "NO_FINALS"
            for path, exists, data in zip(files, present, expected):
                if exists and (not path.is_file() or path.read_bytes() != data):
                    return "AMBIGUOUS"
            return "COMPLETE_PAIR" if all(present) else "PARTIAL"
        except OSError:
            return "AMBIGUOUS"

    outcome = observed_outcome()
    if primary is None and not cleanup_failures and outcome == "COMPLETE_PAIR":
        return

    # Preserve the originating publication exception as __cause__. Cleanup
    # errors cannot silently rewrite a fully-published pair into "no outputs".
    cause = primary or (cleanup_failures[0] if cleanup_failures else
                        OSError("Final output verification was inconclusive"))
    summary = f"{type(cause).__name__}: {cause}; final outcome={outcome}"
    if cleanup_failures:
        summary += "; temporary cleanup failures=" + ", ".join(
            f"{type(exc).__name__}: {exc}" for exc in cleanup_failures
        )
    raise SavePublicationError(
        summary, outcome=outcome, cleanup_failed=bool(cleanup_failures)
    ) from cause
