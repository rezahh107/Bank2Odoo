# Bank2Odoo

**Status:** Working headless **review-candidate** converter for the *documented*
Bank Melli legacy XLS and Bank Mellat CSV shapes. A Persian accountant desktop
GUI, real private Golden acceptance, and accountant Windows acceptance are **not
implemented/proven**. No Odoo integration or financial approval is performed.

This is an offline, local, single-user tool for preparing a minimal Odoo 19
Bank Transactions CSV with exactly `Date,Label,Amount`, **plus a separate private
control report**. It is not an automated accounting categorizer and never
imports/reconciles any transaction in Odoo.

## One command (from checkout root)

After installing `uv` and Python 3.13 (initial setup requires connectivity):

```powershell
uv sync --locked
uv run --locked python -m bank2odoo --input "C:\Private\statement.xls" --output "C:\Private\candidate.csv" --report "C:\Private\control.txt" --source-unit IRR --target-unit IRR --journal "Bank Journal name confirmed by accountant" --decimal-places 0
```

Use `.csv` input for Bank Mellat; the **content**, not extension, selects parser.
Accepted Mellat encodings: UTF-8, UTF-8 BOM, UTF-16 BOM and CP1256; delimiters
comma, semicolon or tab. Melli requires actual binary OLE/XLS; modern XLSX is
not silently accepted. Headers are discovered rather than pinned to row 8.

When monetary units differ, enter the explicitly **accountant-approved** factor
(e.g. verified `TOMAN → IRR` with `--approved-factor 10`); unit selection and
Journal name are entered context, **not verified against Odoo**. Never guess
IRR/TOMAN from bank data. Destination `--decimal-places` must reflect confirmed
Journal/currency precision; amounts requiring rounding are rejected.

The CSV follows the bank's **source row order**. The report records its order,
physical source rows, original columns/IDs, dates/times, exact source-byte SHA,
amounts, balances, tentative associations and outstanding decisions.
One movement → one output row, including fees and reversals. No silent dedup,
classification, rounding or unit conversion. The report is UTF-8 text with
human-readable headings and JSON trace lines; treat it as sensitive.

The converter refuses incomplete/contradictory monetary data, invalid dates,
unknown types, misaligned bank balances, missing units and existing output
files. Incomplete balance support is reported as `NOT_PROVEN`, **never PASS**.
A successful conversion only provides a **review candidate**; it does not mean
accountant approval, absence of previously imported duplicates, or safety of
live Odoo import. Before import, confirm source/journal/account, currency,
period completeness, prior entries, existing Bank Transactions and receipts.

`Run.bat` remains a console launcher displaying explicit GUI-unavailable
status; it is not an accountant-facing GUI. The Python engine can later be
called directly from PySide6 without using a CLI subprocess.

## Verification

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m bank2odoo
```

CI runs on `windows-latest`; synthetic tests write genuine binary BIFF8 XLS and
CSV in private temporary folders, exercise the production pipeline, serialize
CSV/report and compare to independently specified expectations. `xlwt` is used
**only by tests** as a writer of the historical XLS format; actual conversion
uses `xlrd` and calendar conversion uses `persiantools`.

The tracked-file privacy guard remains active; never commit real statements,
identifiers, generated financial CSVs, private Golden or control reports.
The Git guard checks paths and extensions, **not contents**; manually review
all public changes.

## Source policy and evidence limits

Authoritative, private Owner documents (do not copy their private financial
content into GitHub): Bank2Odoo GOAL_AUTHORITY v1.1.2 and NESTEC Bank
Melli/Mellat CSV Conversion Guide v1.0.1. Their published behavior contract is
`Date,Label,Amount` only, exact Decimal amounts, validated Jalali conversion,
per-row trace and explicit review-only status.

The 30-row Bank Melli private reference and 58-row Bank Mellat original are
**not** public fixtures. Local synthetic/Windows CI success is neither a
private source-byte/Golden match nor desktop accountant acceptance.
