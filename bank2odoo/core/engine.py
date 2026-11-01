"""Headless conversion and independent bank-balance controls."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from bank2odoo.banks.reader import SourceRow, read_statement
from bank2odoo.validation.financial import (StatementError, amount, clock,
    exact_scaled, exact_sub, exact_sum, jalali_date, normalized_header, safe_label)


UNITS = {"IRR", "TOMAN"}


@dataclass(frozen=True)
class BalanceGapApproval:
    """A separate, explicit approval scoped to exact source bytes and one gap.

    Approval is not inferred from a date interval, balance mismatch or bank name.
    Keep this outside the public repository when it contains real identifiers.
    """

    source_sha256: str
    preceding_physical_row: int
    following_physical_row: int
    expected_residual: Decimal


@dataclass(frozen=True)
class Context:
    source_unit: str
    target_unit: str
    journal: str
    decimal_places: int = 0
    approved_factor: Decimal | None = None
    balance_gap_approval: BalanceGapApproval | None = None

    def factor(self) -> Decimal:
        if self.source_unit not in UNITS or self.target_unit not in UNITS:
            raise StatementError("Explicit supported source/target unit required (IRR/TOMAN)")
        if not self.journal.strip():
            raise StatementError("An accountant-selected Bank Journal label is required")
        if not 0 <= self.decimal_places <= 9:
            raise StatementError("Destination decimal-places must be between 0 and 9")
        expected = (Decimal("1") if self.source_unit == self.target_unit else
                    Decimal("10") if self.source_unit == "TOMAN" else Decimal("0.1"))
        if self.approved_factor is None:
            if self.source_unit != self.target_unit:
                raise StatementError("Different units require an explicitly accountant-approved conversion factor")
            return expected
        if not self.approved_factor.is_finite() or self.approved_factor != expected:
            raise StatementError("Confirmed conversion factor conflicts with source/target monetary units")
        return expected


@dataclass(frozen=True)
class Movement:
    row: SourceRow
    date: date
    time: tuple[int, int, int] | None
    signed: Decimal
    converted: Decimal
    balance: Decimal | None
    label: str
    reference: str
    kind: str


@dataclass(frozen=True)
class Conversion:
    bank: str
    filename: str
    sha256: str
    encoding: str
    separator: str
    rows: tuple[Movement, ...]
    factor: Decimal
    source_unit: str
    target_unit: str
    journal: str
    debit_total: Decimal
    credit_total: Decimal
    net: Decimal
    balance_status: str
    opening: Decimal | None
    closing: Decimal | None
    ordering: str
    issues: tuple[str, ...]
    decimal_places: int = 0  # Backward-compatible report provenance.


def _movement(row: SourceRow, bank: str, context: Context, factor: Decimal) -> Movement:
    f = row.fields
    label = safe_label(f["description"] or f.get("notes", ""))
    if not label:
        raise StatementError("Missing meaningful bank description")
    date_value = jalali_date(f["date"])
    time = clock(f.get("time", ""))
    balance = amount(f["balance"], required=False)
    if balance is not None and balance < 0:
        # Negative balances can be legitimate overdrafts; preserve them.
        pass
    if bank == "melli":
        raw_amount = amount(f["amount"])
        assert raw_amount is not None
        if raw_amount <= 0:
            raise StatementError("Bank Melli amount must be a positive magnitude; signed/zero correction needs review")
        movement_type = normalized_header(f["kind"])
        if movement_type in ("برداشت", "بدهکار"):
            signed = raw_amount.copy_negate()
        elif movement_type in ("واریز", "بستانکار"):
            signed = raw_amount.copy_abs()
        else:
            raise StatementError(f"Unrecognized Bank Melli transaction type: {f['kind']!r}")
    else:
        debit = amount(f["debit"], required=False)
        credit = amount(f["credit"], required=False)
        debit, credit = debit or Decimal(0), credit or Decimal(0)
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise StatementError("Bank Mellat debit/credit sides must have exactly one positive value")
        signed = exact_sub(credit, debit)
    return Movement(row, date_value, time, signed,
                    exact_scaled(signed, factor, context.decimal_places), balance,
                    label, f.get("reference", ""), f.get("kind", ""))


def _balances(
    rows: tuple[Movement, ...],
    approval: BalanceGapApproval | None = None,
    *,
    source_sha256: str | None = None,
) -> tuple[str, Decimal | None, Decimal | None, str, list[str]]:
    issues: list[str] = []
    if approval is not None:
        if source_sha256 is None or approval.source_sha256 != source_sha256:
            raise StatementError("Balance-gap approval does not match exact source SHA-256")
        if (approval.preceding_physical_row < 1 or approval.following_physical_row < 1
                or approval.preceding_physical_row >= approval.following_physical_row
                or not approval.expected_residual.is_finite()
                or approval.expected_residual == 0):
            raise StatementError("Invalid explicitly approved balance-gap boundary/residual")
        if len(rows) < 4:
            raise StatementError("Approved gap requires two verifiable balance segments")
    if not all(r.balance is not None for r in rows):
        if approval is not None:
            raise StatementError("Cannot verify approved gap with missing source balances")
        return "NOT_PROVEN: missing source balances", None, None, "unknown", ["Missing balance(s); no full balance proof"]
    if len(rows) < 2:
        return "NOT_PROVEN: one movement", None, None, "unknown", ["One movement cannot establish bank ordering"]
    if any(a.date == b.date and (a.time is None or b.time is None)
           for a, b in zip(rows, rows[1:])):
        if approval is not None:
            raise StatementError("Approved gap requires provable source chronological order")
        return "NOT_PROVEN: incomplete time/order", None, None, "unknown", ["Same-date rows without complete times"]
    keys = [(r.date, r.time or (0, 0, 0)) for r in rows]
    forward = all(a <= b for a, b in zip(keys, keys[1:]))
    reverse = all(a >= b for a, b in zip(keys, keys[1:]))
    if forward == reverse:
        if approval is not None:
            raise StatementError("Approved gap requires provable source chronological order")
        return "NOT_PROVEN: ambiguous or unordered timestamps", None, None, "unknown", ["Chronological source order is unproven"]

    approved_index: int | None = None

    def verify_transition(previous: Movement, current: Movement,
                          residual: Decimal, pair_index: int) -> None:
        nonlocal approved_index
        if residual == 0:
            return
        if (approval is not None and approved_index is None
                and previous.row.physical_row == approval.preceding_physical_row
                and current.row.physical_row == approval.following_physical_row
                and residual == approval.expected_residual):
            if keys[pair_index] <= keys[pair_index + 1]:
                raise StatementError(
                    "Approved Bank Melli gap boundary requires strictly descending timestamps "
                    f"at source rows {previous.row.physical_row}/{current.row.physical_row}"
                )
            approved_index = pair_index
            return
        raise StatementError(
            f"Consecutive balance mismatch at source rows "
            f"{previous.row.physical_row}/{current.row.physical_row}"
        )

    if forward:
        for i, (previous, current) in enumerate(zip(rows, rows[1:])):
            assert previous.balance is not None and current.balance is not None
            residual = exact_sub(exact_sub(current.balance, previous.balance), current.signed)
            verify_transition(previous, current, residual, i)
        first, last = rows[0], rows[-1]
        assert first.balance is not None and last.balance is not None
        opening, closing = exact_sub(first.balance, first.signed), last.balance
        order = "oldest-to-newest"
    else:
        for i, (newer, older) in enumerate(zip(rows, rows[1:])):
            assert newer.balance is not None and older.balance is not None
            residual = exact_sub(exact_sub(newer.balance, older.balance), newer.signed)
            verify_transition(newer, older, residual, i)
        first, last = rows[0], rows[-1]
        assert first.balance is not None and last.balance is not None
        opening, closing = exact_sub(last.balance, last.signed), first.balance
        order = "newest-to-oldest"

    if approval is not None:
        if order != "newest-to-oldest":
            raise StatementError("Bank Melli historical gap requires original newest-to-oldest source order")
        if approved_index is None:
            raise StatementError("Approved balance gap not found in exact source rows")
        if approved_index == 0 or approved_index == len(rows) - 2:
            raise StatementError("Approved gap requires at least two movements in each segment")
        before_count = approved_index
        after_count = len(rows) - approved_index - 2
        issues.append(
            f"DECLARED HISTORICAL GAP (not independently attested by software): source rows "
            f"{approval.preceding_physical_row}/{approval.following_physical_row}; "
            f"source-unit residual {approval.expected_residual}. "
            f"Verified {before_count}+{after_count} within-segment transitions; "
            "whole-period opening/closing and continuity NOT_PROVEN."
        )
        return (
            f"NOT_PROVEN: explicitly declared historical gap; "
            f"{before_count}+{after_count} strict within-segment transitions",
            None, None, order, issues,
        )

    net = exact_sum(r.signed for r in rows)
    if exact_sub(closing, opening) != net:
        raise StatementError("Closing minus inferred opening does not equal source movement net")
    return f"PASS: {len(rows)-1} consecutive balance transitions", opening, closing, order, issues

def convert(path: Path, context: Context) -> Conversion:
    factor = context.factor()  # fail without opening any statement when units unapproved
    raw = path.read_bytes()
    if not raw:
        raise StatementError("Empty bank statement")
    source_sha256 = sha256(raw).hexdigest()
    source = read_statement(path, raw)
    if context.balance_gap_approval is not None and source.bank != "melli":
        raise StatementError("Historical gap declaration is supported for Bank Melli only")
    rows = []
    for item in source.rows:
        try:
            rows.append(_movement(item, source.bank, context, factor))
        except StatementError as exc:
            raise StatementError(f"{source.bank} {item.sheet}, physical row {item.physical_row}: {exc}") from exc
    movements = tuple(rows)  # retain each physical movement, preserve original order
    balance_status, opening, closing, ordering, issues = _balances(
        movements, context.balance_gap_approval, source_sha256=source_sha256
    )
    seen: dict[tuple, int] = {}
    for mov in movements:
        k = (mov.date, mov.time, mov.signed, mov.reference, mov.label)
        if k in seen:
            issues.append(f"POSSIBLE duplicate, retained: source rows {seen[k]} and {mov.row.physical_row}")
        else:
            seen[k] = mov.row.physical_row
    by_ref: dict[str, list[Movement]] = {}
    for mov in movements:
        # Only tentative, same-day associations; reference alone is NOT a unique identifier.
        if mov.reference:
            by_ref.setdefault(mov.reference, []).append(mov)
    for ref, group in by_ref.items():
        days = {m.date for m in group}
        if len(group) > 1 and len(days) == 1:
            issues.append("TENTATIVE shared-reference association: source rows " +
                          ", ".join(str(m.row.physical_row) for m in group))
    debits = exact_sum(m.signed.copy_abs() for m in movements if m.signed < 0)
    credits = exact_sum(m.signed for m in movements if m.signed > 0)
    return Conversion(source.bank, path.name, source_sha256, source.encoding,
                      source.separator, movements, factor, context.source_unit, context.target_unit,
                      context.journal, debits, credits, exact_sub(credits, debits), balance_status,
                      opening, closing, ordering, tuple(issues), context.decimal_places)
