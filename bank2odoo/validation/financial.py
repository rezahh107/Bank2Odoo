"""Exact, deliberately conservative interpretation of Iranian statement fields."""

from datetime import date
from decimal import (Decimal, DecimalException, Inexact, InvalidOperation,
                     MAX_EMAX, MIN_EMIN, Rounded, localcontext)
import re
import unicodedata

from persiantools.jdatetime import JalaliDate


class StatementError(ValueError):
    """A source ambiguity or financial inconsistency that forbids a CSV."""


DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def ascii_digits(value: str) -> str:
    return str(value).translate(DIGITS)


def normalized_header(value: str) -> str:
    text = unicodedata.normalize("NFKC", ascii_digits(value)).translate(str.maketrans({"ي": "ی", "ك": "ک"}))
    text = re.sub(r"[\u064b-\u065f\u0670\u200c\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def amount(value: str, *, required: bool = True) -> Decimal | None:
    raw = ascii_digits(str(value)).strip().replace("\u00a0", "").replace("\u202f", "")
    raw = raw.replace("\u066c", ",").replace("\u066b", ".")
    raw = re.sub(r"\s+", "", raw)
    if not raw:
        if not required:
            return None
        raise StatementError("Missing monetary amount")
    # Use comma only in well-formed three-digit thousands groups, never as a decimal guess.
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        raise StatementError(f"Invalid/ambiguous numeric format: {value!r}")
    try:
        parsed = Decimal(raw.replace(",", ""))
    except InvalidOperation as exc:
        raise StatementError(f"Invalid monetary amount: {value!r}") from exc
    if not parsed.is_finite():
        raise StatementError("Non-finite monetary amount")
    return parsed


def jalali_date(value: str) -> date:
    value = ascii_digits(str(value)).strip().replace("-", "/")
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
    if not m:
        raise StatementError(f"Missing/invalid Jalali date: {value!r}")
    year, month, day = map(int, m.groups())
    try:
        return JalaliDate(year, month, day).to_gregorian()
    except (ValueError, OverflowError) as exc:
        raise StatementError(f"Impossible Jalali date: {value!r}") from exc


def clock(value: str) -> tuple[int, int, int] | None:
    s = ascii_digits(str(value)).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if not m:
        raise StatementError(f"Ambiguous bank transaction time: {value!r}")
    h, minute, second = map(int, (m.group(1), m.group(2), m.group(3) or "0"))
    if h > 23 or minute > 59 or second > 59:
        raise StatementError(f"Impossible bank transaction time: {value!r}")
    return (h, minute, second)


def safe_label(value: str) -> str:
    s = re.sub(r"[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e]", " ", value)
    return re.sub(r"\s+", " ", s).strip().translate(str.maketrans({"ي": "ی", "ك": "ک"}))



def _exact_binary(left: Decimal, right: Decimal, operation: str) -> Decimal:
    """Compute without the caller's default Decimal precision or implicit rounding."""
    if not left.is_finite() or not right.is_finite():
        raise StatementError("Non-finite monetary operand")
    if operation == "multiply":
        precision = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2
    else:
        # Cover all integral/fractional positions (including distant exponents)
        # and the possible extra carry digit.
        highest = max(0, left.adjusted(), right.adjusted())
        lowest = min(0, left.as_tuple().exponent, right.as_tuple().exponent)
        precision = highest - lowest + 3
    try:
        with localcontext() as ctx:
            ctx.prec = precision
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            ctx.traps[InvalidOperation] = True
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            if operation == "add":
                return left + right
            if operation == "subtract":
                return left - right
            return left * right
    except (DecimalException, ValueError) as exc:
        raise StatementError(f"Cannot represent exact monetary {operation}") from exc


def exact_add(left: Decimal, right: Decimal) -> Decimal:
    return _exact_binary(left, right, "add")


def exact_sub(left: Decimal, right: Decimal) -> Decimal:
    return _exact_binary(left, right, "subtract")


def exact_sum(values) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = exact_add(total, value)
    return total


def exact_scaled(value: Decimal, factor: Decimal, decimal_places: int) -> Decimal:
    result = _exact_binary(value, factor, "multiply")
    # Quantizing is a precision check only. Removing zero decimals is allowed;
    # dropping any nonzero decimal is forbidden even if a default context would
    # silently round it. Return the untouched, exact multiplication result.
    unit = Decimal((0, (1,), -decimal_places))
    precision = max(len(result.as_tuple().digits),
                    result.adjusted() + 1 + decimal_places, 1) + 2
    try:
        with localcontext() as ctx:
            ctx.prec = precision
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            ctx.traps[InvalidOperation] = True
            ctx.traps[Inexact] = True
            result.quantize(unit)
    except (DecimalException, ValueError) as exc:
        raise StatementError(
            f"Amount {result} exceeds confirmed {decimal_places} decimal places "
            "or cannot be represented exactly; no rounding permitted"
        ) from exc
    return result
