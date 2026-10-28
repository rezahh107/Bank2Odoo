# Bank2Odoo

**Status:** Working headless conversion engine plus a Persian PySide6 Widgets
desktop interface for preparing **review candidates** from the documented Bank
Melli legacy XLS and Bank Mellat CSV formats. Synthetic GUI/engine tests do not
prove private-bank Golden acceptance or usability on an accountant's Windows
machine. No Odoo integration or financial approval is performed.

This is an offline, local, single-user tool for preparing a minimal Odoo 19
Bank Transactions CSV with exactly `Date,Label,Amount`, **plus a separate private
control report**. It is not an automated accounting categorizer and never
imports/reconciles any transaction in Odoo.

## Accountant desktop application (Windows)

One-time technician setup (Internet required for installing prerequisites):

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run `uv python install 3.13`.
2. In the downloaded Bank2Odoo folder, run `uv sync --locked` once while online.
3. Double-click **Run.bat**. Normal launching/conversion uses `uv run --offline --locked`; no Odoo or Internet connection is required once setup is complete.

In the Persian window select an actual Melli XLS or Mellat CSV, confirm the **source and target units, journal, currency precision and (if units differ) approved factor**, then select **اعتبارسنجی و تبدیل**. Review the count, totals, balance status and flagged uncertainties. Choose a **private folder outside this checkout**, then click **ذخیره CSV و گزارش کنترل**. Both files must be new: the program refuses overwriting and does not independently approve any Odoo import.

A `PASS` balance check is limited to observed consecutive balances; `NOT_PROVEN` means a complete proof is unavailable, not necessarily an error. A generated candidate still requires accountant review, independent approval and checking for past imports before any manual Odoo import. Technical diagnostics are optional and hidden by default. Closing a busy window requires waiting for the current operation; the stop request discards its result after the active phase.

This is **not** a standalone EXE. If Run.bat says prerequisites are missing, ask the technician to perform the one-time setup again. Do not store actual statements, output CSVs or private reports in the public source repository.

## Qt Widgets visual modernization (Windows 11 direction)

The accountant workflow remains the same: file selection → automatic content-based
bank detection → financial context and **explicit, initially unchecked** approval →
conversion/review → private paired save. The window now uses separated, readable
sections, bounded field widths, row wrapping on smaller windows, LTR isolation for
Latin amounts/paths, distinct native action sizes and an independent 52 px-high
clickable approval control. The complete prior global QSS skin was removed so native
combos, focus, check indicators, buttons and disabled states are drawn by Qt style.

At launch, `QStyleFactory.keys()` is inspected on Windows. If the installed
PySide6-Essentials 6.11.2 Qt exposes `windows11`, Qt is configured to use that
native platform style. Otherwise the built-in `Fusion` style is the predictable
fallback; non-Windows environments retain their system style. Launch diagnostics
print the available styles, chosen effective style and resolved font. This is
*capability detection*, not a claim that Windows 11 native style renders correctly
on every machine. The Windows CI native-QPA probe can check availability and widget
construction, but **cannot replace human viewing on the actual Windows 11 display**.

Installed Vazirmatn is preferred at 11 pt, then Tahoma or the system font.
The app does not bundle a font: the Owner already observed Vazirmatn installed,
and the available evidence does not isolate a font rasterization defect. Larger
headings, stronger primary actions and better spacing address the separate visual
hierarchy problem. Verify Persian glyphs and 100%/125%/150% display scaling on
the target Windows workstation before treating visual acceptance as complete.
No financial validation, approval rule, SHA binding, serialization or threading
contract was changed.

## Developer CLI (from checkout root)

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

`Run.bat` starts the Persian Qt interface directly. The developer CLI remains
available at `python -m bank2odoo` and the GUI at `python -m bank2odoo.ui`.
The GUI calls the core functions directly, never a CLI subprocess.

## Verification

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m bank2odoo
```

CI runs on `windows-latest`, including offscreen Qt Widgets interaction tests;
offscreen Qt does **not** prove real Windows interactive use or a human UX review.
Synthetic tests write genuine binary BIFF8 XLS and
CSV in private temporary folders, exercise the production pipeline, serialize
CSV/report and compare to independently specified expectations. `xlwt` is used
**only by tests** as a writer of the historical XLS format; actual conversion
uses `xlrd` and calendar conversion uses `persiantools`.

### Frozen Phase 1 oracle / actual Phase 2 synthetic acceptance

`tests/test_converter_oracle.py` generates the **unchanged** 30-movement Melli
BIFF8 XLS and 58-movement Mellat CSV, invokes the production `convert()` and
`save_candidate()` functions, then compares the saved three-column CSV and
the actual private textual/JSON-line report against the frozen Phase 1 checker.
The synthetic test-only adapter extracts financial totals, source identity,
physical rows, dates, balances and original columns from the **actual report**,
not from the expected files. It checks the literal output CSV bytes separately.

Only synthetic-specific tags (fictional approval, unconfirmed journal warnings)
come from test context. Fee/correction tags are derived from the clearly marked
fictional source descriptions; they do **not** prove the product implements a
general bank-transaction classifier, accountant approval or confirmed
fee/correction associations. A missing report field cannot be fabricated
from the frozen oracle; evidence unavailability and mismatches are distinct.
The production accountant report remains human-readable and unmodified.

The generated Melli file has an explicit `پایان گزارش` footer. Its support
was added narrowly to the bank reader; unexpected non-transaction text still
fails closed. These synthetic tests establish neither private bank-file
acceptance nor Windows accountant-device/Odoo integration.

The tracked-file privacy guard remains active; never commit real statements,
identifiers, generated financial CSVs, private Golden or control reports.
The Git guard checks paths and extensions, **not contents**; manually review
all public changes.

## Source policy and evidence limits

Authoritative, private Owner documents (do not copy their private financial
content into GitHub): Bank2Odoo GOAL_AUTHORITY v1.1.13 and NESTEC Bank
Melli/Mellat CSV Conversion Guide v1.0.1. Their published behavior contract is
`Date,Label,Amount` only, exact Decimal amounts, validated Jalali conversion,
per-row trace and explicit review-only status.

The 30-row Bank Melli private reference and 58-row Bank Mellat original are
**not** public fixtures. Local synthetic/Windows CI success is neither a
private source-byte/Golden match nor desktop accountant acceptance.
