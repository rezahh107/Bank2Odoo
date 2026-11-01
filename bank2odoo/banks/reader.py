"""Bank-specific source extraction; no accounting decisions or Odoo coupling."""

from dataclasses import dataclass
import csv
import io
from pathlib import Path

from bank2odoo.validation.financial import StatementError, normalized_header

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")

REQUIRED = {
    "melli": {"date": ("تاریخ",), "kind": ("نوع",), "amount": ("مبلغ",),
              "description": ("شرح", "توضیحات")},
    "mellat": {"date": ("تاریخ",), "debit": ("مبلغ گردش بدهکار",),
               "credit": ("مبلغ گردش بستانکار",),
               "description": ("شرح",)},
}
OPTIONAL = {
    "melli": {"balance": ("مانده",), "time": ("زمان", "ساعت"), "report_row": ("ردیف",),
              "reference": ("شماره پیگیری",), "details": ("اطلاعات تکمیلی",),
              "notes": ("توضیحات",)},
    "mellat": {"balance": ("مانده",), "time": ("زمان", "ساعت"), "report_row": ("ردیف",),
               "reference": ("شماره سریال",), "details": ("واریز کننده/ذینفع", "واریز کننده / ذینفع")},
}


@dataclass(frozen=True)
class SourceRow:
    physical_row: int
    sheet: str
    fields: dict[str, str]
    original: dict[str, str]


@dataclass(frozen=True)
class Source:
    bank: str
    rows: tuple[SourceRow, ...]
    encoding: str
    separator: str


def _column_map(headers: list[str], bank: str) -> dict[str, int] | None:
    names = [normalized_header(item) for item in headers]
    cols: dict[str, int] = {}
    for key, options in REQUIRED[bank].items():
        # Description is allowed to have both the bank's primary "شرح" and
        # supplementary "توضیحات" columns. Prefer the primary label, rather
        # than falsely rejecting a genuine Melli statement as duplicate.
        chosen = None
        for candidate in options:
            indexes = [i for i, item in enumerate(names) if item == normalized_header(candidate)]
            if len(indexes) > 1:
                raise StatementError(f"Duplicate/ambiguous {bank} header {key}")
            if indexes and chosen is None:
                chosen = indexes[0]
        if chosen is None:
            return None
        cols[key] = chosen
    for key, options in OPTIONAL[bank].items():
        indexes = [i for i, item in enumerate(names) if item in {normalized_header(a) for a in options}]
        if len(indexes) > 1:
            raise StatementError(f"Duplicate/ambiguous {bank} optional header {key}")
        if indexes:
            cols[key] = indexes[0]
    return cols


def _extract(table: list[tuple[int, list[str]]], bank: str, sheet: str) -> tuple[SourceRow, ...] | None:
    matches = [(i, _column_map(values, bank)) for i, (_, values) in enumerate(table)]
    matched = [(i, mapping) for i, mapping in matches if mapping is not None]
    if not matched:
        return None
    if len(matched) != 1:
        raise StatementError(f"More than one {bank} header row in {sheet}")
    header_idx, mapping = matched[0]
    assert mapping is not None
    header = table[header_idx][1]
    result: list[SourceRow] = []
    seen_footer = False
    for physical, cells in table[header_idx + 1:]:
        if not any(str(v).strip() for v in cells):
            continue
        populated = [str(value).strip() for value in cells if str(value).strip()]
        first = normalized_header(populated[0])
        if first.startswith(("جمع", "مجموع", "کل گردش", "پایان گزارش")):
            # A real footer is a standalone marker. Additional populated
            # columns may contain a bank movement or financial totals; neither
            # may be silently removed based only on the marker's prefix.
            if len(populated) != 1:
                raise StatementError(
                    f"Ambiguous financial-bearing footer at {sheet}:{physical}; "
                    "review the populated source fields"
                )
            seen_footer = True
            continue
        if seen_footer:
            raise StatementError(f"Unexpected data after total/footer at {sheet}:{physical}")
        fields = {key: str(cells[i]).strip() if i < len(cells) else "" for key, i in mapping.items()}
        if not fields["date"]:
            raise StatementError(f"Missing transaction date or unidentified footer at {sheet}:{physical}")
        original = {f"{header[i] if str(header[i]).strip() else 'column_'+str(i+1)} [{i+1}]": str(value)
                    for i, value in enumerate(cells)}
        result.append(SourceRow(physical, sheet, fields, original))
    if not result:
        raise StatementError(f"No transactions below {bank} header in {sheet}")
    return tuple(result)


def _xls_text(cell: object) -> str:
    # XLS financial cells are stored as binary floating point; represent the
    # decoded cell faithfully with str(), never apply a guessed money format.
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell).strip()


def _read_melli(raw: bytes) -> Source:
    try:
        import xlrd
        workbook = xlrd.open_workbook(file_contents=raw, on_demand=True)
    except Exception as exc:
        raise StatementError(f"Invalid/unreadable legacy XLS: {type(exc).__name__}") from exc
    try:
        candidates = []
        for sheet in workbook.sheets():
            table = [(r + 1, [_xls_text(sheet.cell_value(r, c)) for c in range(sheet.ncols)])
                     for r in range(sheet.nrows)]
            parsed = _extract(table, "melli", sheet.name)
            if parsed is not None:
                candidates.append(parsed)
        if len(candidates) != 1:
            raise StatementError(f"Expected one Bank Melli transaction sheet; got {len(candidates)}")
        return Source("melli", candidates[0], "binary XLS", "cells")
    finally:
        workbook.release_resources()


def _read_mellat(raw: bytes) -> Source:
    # Try verifiable encodings, then recognizable header structure; never use
    # replace/ignore decoding, which would silently alter Persian descriptions.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif raw.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig",)
    else:
        encodings = ("utf-8", "cp1256")
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="strict")
        except UnicodeError:
            continue
        if "\x00" in text:
            continue
        for sep in (",", ";", "\t"):
            try:
                reader = csv.reader(io.StringIO(text, newline=""), delimiter=sep, strict=True)
                table = []
                previous_end = 0
                for row in reader:
                    physical_start = previous_end + 1
                    previous_end = reader.line_num
                    if len(row) > 200:
                        raise StatementError("Unreasonable bank CSV column count")
                    # reader.line_num points to physical END of CSV record.
                    table.append((physical_start, row))
                parsed = _extract(table, "mellat", "CSV")
            except csv.Error as exc:
                raise StatementError(f"Broken bank CSV: {exc}") from exc
            if parsed is not None:
                return Source("mellat", parsed, encoding, repr(sep))
    raise StatementError("No recognized Bank Mellat CSV headers/encoding/delimiter")


def read_statement(path: Path, raw: bytes) -> Source:
    if raw.startswith(OLE_MAGIC):
        return _read_melli(raw)
    if raw.startswith(b"PK\x03\x04"):
        raise StatementError("XLSX/ZIP is not an approved Bank Melli legacy XLS input")
    return _read_mellat(raw)
