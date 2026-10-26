# Bank2Odoo engineering entrypoint

- Read `README.md` first, then the Owner-adopted Bank2Odoo goal and `NESTEC_BANK_MELLI_MELLAT_CSV_CONVERSION_GUIDE_v1.0.1` named there before implementing bank behavior. The external Owner goal outranks this file.
- This is a personal offline Windows tool. The core must not depend on PySide6 or Odoo. Bank adapters belong in `bank2odoo/banks`; shared logic in `core`; validation and reports in their respective packages; future Qt Widgets UI in `ui`.
- Never fabricate conversion results. Preserve every real bank movement, including fees/corrections; use `Decimal`, validate units and Jalali dates, and fail closed on ambiguity. CSV alone never authorizes live import.
- Never commit actual statements, account identifiers, or private control reports, even if `.gitignore` is bypassed. Public fixtures must be synthetic and reviewed.
- From the repository root: `uv sync --locked`; verification: `uv run --locked python -m unittest discover -s tests -v`; smoke run: `uv run --locked python -m bank2odoo`.
- Report what actually ran and what remains unverified. Do not merge, release, or change Odoo/financial data without separate authorization.
