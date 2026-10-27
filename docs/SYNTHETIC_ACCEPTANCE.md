# Phase 1 — independent synthetic reference qualification

This suite was authored **without checking out, importing, or deriving results from PR #2**. No real bank account, name, ID, transaction, private Golden or private report is included. Source amounts, labels, references and dates are fictional. It checks its own reference and checker; **it does not run or approve any converter**.

## Run

From the repository root (Python 3.13 in the existing uv environment):

```powershell
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

`tests/test_synthetic_acceptance.py` is automatically included in the existing Windows GitHub Actions command. No new dependencies or workflow are needed. The tests use `tempfile.TemporaryDirectory`; generated `.xls`/`.csv` and synthetic candidate reports are never committed.

## Frozen reference (review this diff carefully before changing)

- `tests/acceptance/source_ledger.json` — **independently specified fictional source ledger**, 30 Melli movements and 58 Mellat movements, with original dates, physical row numbers, descriptions, serials, directions, amounts and running balances.
- `tests/acceptance/frozen_expected.json` — **frozen acceptance oracle** with all destination rows, signed amounts, Gregorian dates, source-to-output mappings, summaries, units and explicitly non-production acceptance status.
- `tests/acceptance/expected_melli_csv.txt` and `expected_mellat_csv.txt` — exact readable `Date,Label,Amount` reference CSV text, stored as `.txt` to respect the existing strict ignore of `.csv` files. The checker compares semantic CSV fields, so valid CRLF/LF record separators are both allowed.

The `.json` and `.txt` references are ordinary immutable-by-convention, version-controlled files. The generator never writes them and the test never updates them. Correct an oracle defect only after documented independent requalification; **never adjust oracle expectations just to match PR #2**.

## Format and financial contract

| Property | Melli | Mellat |
|---|---:|---:|
| Format | Real OLE compound/BIFF8 `.xls`, non-fixed header at physical row 5 | 12-column UTF-8 BOM `.csv` with header at physical row 3 |
| Independent bank movements | 30 | 58 |
| Debits / credits | 21 / 9 | 43 / 15 |
| Fee debits (within debits) | 10 | 13 |
| Correction credits (within credits) | 2 | 2 |
| Consecutive verified balance transitions | 29 | 57 |
| Physical order | newest → oldest | oldest → newest |
| Opening balance (fictional IRR) | 9,000,000 | 14,000,000 |
| Total debit / credit (fictional IRR) | 230,344 / 527,550 | 1,196,326 / 1,677,609 |
| Net / closing balance (fictional IRR) | +297,206 / 9,297,206 | +481,283 / 14,481,283 |

All positive tests use **fictional IRR→IRR, factor 1, `SYNTHETIC_TEST_ONLY`**; this is not a real accountant approval. Journal is explicitly `UNCONFIRMED`; only `CANDIDATE_TEST_ONLY` status is allowed. Reference warnings also state that fee associations and correction relationships remain unconfirmed. The date range is fictional Mehr 1405; `1405/07/01 = 2026-09-23`. The Melli file has preamble/footer, realistic Persian header labels and 14 columns; both files have distinct physical row references. The Mellat serials deliberately retain leading zeros. Supplemental one-row CP1256 and UTF-8 BOM cases confirm those encodings can be generated/read back, not that a production converter supports them. Transfer/fee shared references and near timestamps are **clues**, not accounting permission to merge movements; correlation remains a human-review concern.

## What is actually checked

`fixtures.py` independently writes legacy binary XLS (OLE signature, BIFF8 workbook and Persian Unicode cell records) and UTF-8 BOM/CP1256 CSV. `probe.py` has a separate read-only, narrow OLE/BIFF8 decoder to inspect all expected Melli rows; it is **not a production bank reader**. The full Mellat CSV is read back using the standard `csv` module. `checker.py` calculates ledger invariants with `Decimal`, tests source chronological balance chains, validates the frozen two-file oracle and compares any externally produced `Date,Label,Amount` CSV plus JSON report strictly row-by-row.

The checker requires the report to contain: `bank`, actual `source_sha256`, `journal`, `source_unit`, `destination_unit`, `factor`, `fictional_approval`, `acceptance_status`, `warnings`, count/debit/credit/fee/correction totals, opening/closing balance and full `trace` mapping. Trace entries contain all keys declared in `EXPECTED_FIELDS`. Missing evidence raises `EvidenceUnavailable`, while a contractual mismatch raises `ContractMismatch`. The 24 mutation types are run for **each bank**, covering amount/sign/precision, missing/extra/reordered movement, Gregorian date, descriptions, trace mapping, balance, fee/correction categories, units, totals, file hash, false status/warnings and wrong header. Source-ledger mutations also demonstrate qualification rejects inconsistent inputs.

**Important:** the current checker JSON shape is a Phase 2 *acceptance adapter contract*, not a claim about the current PR #2 report format. In Phase 2, a small test adapter should map the converter's **actual private report** to this shape without discarding fields, hiding errors, modifying financial values or regenerating oracle files. Preserve actual source row/transaction IDs and source bytes/hash. If report evidence is unavailable, do not create a synthetic PASS report: classify it NOT_VERIFIED. Do not infer a production-ready status from success of these tests.

## Phase 2 handoff

1. Obtain Owner review of this focused Phase 1 PR, then merge **only if expressly authorized**.
2. In a separate mission integrate PR #2 with the latest merged main; generate the same synthetic source files using `render_melli`/`render_mellat` in temporary directories and **invoke the actual converter**.
3. Compare the produced CSV and adapted private report against `check_result(bank, csv_path, report_path, source_path)` without modifying the frozen `.json`/`.txt` expectations. Investigate contract disagreements against original source semantics, not the historical private Melli Golden.
4. Run the exact-Head Windows CI on the converter and report that evidence independently. Perform private original-file acceptance and accountant unit/Journal sign-off outside public GitHub/CI; Windows BAT/user-flow and real Odoo behavior remain separate.

**Limitations:** examples do not cover the full range of historical bank exports, exotic date/locale patterns, Jalali leap boundaries, XLSX, real CP1256 full-size statements, ambiguous direction or monetary-unit resolution, production import or Odoo reconciliation. A narrow local OLE/BIFF8 reader proves only the authored subset of the format, not compatibility with every Windows Excel or banking exporter. A passing Phase 1 suite confirms its own static assumptions and mutation sensitivity; the converter remains NOT_RUN.
