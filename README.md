# Bank2Odoo

**Status: repository foundation only — no converter or desktop GUI is implemented yet.**

Bank2Odoo is planned as a small, offline Windows desktop application for a NESTEC accountant. Its future job is to convert Iranian bank statements into a **reviewable** CSV for Odoo 19 Bank Transactions, plus a separate **private control report**. It does not connect to Odoo, approve any transaction, or perform accounting reconciliation.

## Supported scope and boundaries

- **Planned initial sources:** Bank Melli (legacy XLS) and Bank Mellat (CSV), with XLSX support if needed. Identify file formats from actual content, not just the extension.
- **Future target CSV:** exactly `Date,Label,Amount` in that order; UTF-8, comma-delimited and correctly CSV-quoted. Date is Gregorian `YYYY-MM-DD`; debits are negative and credits positive. The private control report must preserve row-by-row source traceability, balances, exceptions and approvals outstanding.
- **Safety requirements:** exact `Decimal` amounts; explicitly confirmed source/destination units and destination Journal; correct Jalali-to-Gregorian dates; preserve separate movements, fees and corrections. Never silently discard suspected duplicates, guess monetary units, round values or label a CSV ready for live import.
- **Not in scope:** direct Odoo integration, production import authorization, account assignment/reconciliation, server, database, multi-user service, EXE/PyInstaller packaging or automatic financial decisions.

Source-of-truth documents (kept in the **authorized private** project workspace, not published here):

- `01_BANK2ODOO_OWNER_ADOPTED_DESTINATION_20261026` (Owner-adopted goal).
- `NESTEC_BANK_MELLI_MELLAT_CSV_CONVERSION_GUIDE_v1.0.1` (bank conversion contract).

Ask the Owner for authorized access to these documents before implementing bank processing. Do **not** copy private samples or control reports into this repository. A future converter must be validated against authorized private reference outputs outside GitHub/CI before real use.

## Setup and current execution

Requirements: Windows for the intended accountant workflow; [uv](https://docs.astral.sh/uv/getting-started/installation/) installed and available on `PATH`. Python 3.13 will be acquired by uv on first online setup if unavailable. This foundation has **no third-party runtime/test dependencies**; PySide6/Qt Widgets is the accepted **future GUI** choice, not a currently installed GUI.

From a terminal **in the repository root**:

```powershell
uv python install 3.13
uv sync --locked
uv run --locked python -m bank2odoo
```

The last command **prints a foundation-only status** and exits normally; it does not ask for bank files, create a CSV or launch a GUI. On Windows, `Run.bat` changes to its own folder, runs the same entrypoint through uv and leaves the console open so the status is visible. It is not a converter launcher yet. Once Python, uv and dependencies are locally available, they can be reused offline; initial bootstrap may require internet.

This is an **uv-managed application checkout** (`package = false`), not a published installable wheel or command on the global `PATH`. Run commands from this checkout; changing packaging is only needed when distribution requirements become real.

## Verify a change

The single automated verification command (from repository root) is:

```powershell
uv run --locked python -m unittest discover -s tests -v
```

It executes the real Python module in a subprocess (including version and unsupported-argument failure), checks module boundaries import without GUI dependencies, and rejects obviously sensitive file types or private paths **already tracked by Git**. Nonzero exit means failure. The safety check does not classify content and **cannot guarantee** that a malicious or misnamed private document is absent: manually review every staged file before pushing.

CI runs this same verification plus an entrypoint smoke on `windows-latest`. A workflow file is not proof of a green CI run or of Windows `Run.bat` behavior; the batch launcher still needs real Windows testing.

## Minimal layout

- `bank2odoo/cli.py` and `__main__.py`: status-only entrypoint.
- `bank2odoo/core/`: future bank-independent conversion (must remain independent of GUI).
- `bank2odoo/banks/`: future Bank Melli / Bank Mellat adapters.
- `bank2odoo/validation/`: future fail-closed input and financial checks.
- `bank2odoo/reporting/`: future private control-report generation.
- `bank2odoo/ui/`: future Persian RTL PySide6/Qt Widgets interface.
- `tests/`: executable smoke and repository-safety checks.

No real parsing, currency handling, calendar conversion, balance-chain checking, report creation or UI exists yet. No real Odoo/test import is attempted by this foundation.

## Privacy and contribution boundary

The repository is **public**. `.gitignore` excludes typical bank statements, generated CSVs, control reports, caches and environments; never override it to publish real financial inputs/outputs or personally identifying financial information. The intended first implementation should use carefully reviewed **synthetic** tests and external private acceptance runs. Financial releases and real Odoo imports require separate Owner/accountant decisions. No license is asserted by this initial foundation.
