"""Headless conversion CLI; the separate Persian GUI is at bank2odoo.ui."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting.output import save_candidate
from bank2odoo.validation.financial import StatementError
from bank2odoo.version import VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bank2odoo", description=("Headless bank statement review-candidate CLI; "
                    "separate Persian GUI: python -m bank2odoo.ui; no Odoo import"))
    parser.add_argument("--version", action="version", version=f"Bank2Odoo {VERSION} (headless candidate engine)")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, help="New 3-column CSV path (no overwrite)")
    parser.add_argument("--report", type=Path, help="New PRIVATE plain-text report path (no overwrite)")
    parser.add_argument("--source-unit", choices=("IRR", "TOMAN"))
    parser.add_argument("--target-unit", choices=("IRR", "TOMAN"))
    parser.add_argument("--journal", help="Accountant-chosen Bank Journal name; not independently verified")
    parser.add_argument("--decimal-places", type=int, default=0, help="Confirmed Odoo Journal currency precision")
    parser.add_argument("--approved-factor", help="Required when units differ; exact factor (10 or 0.1)")
    args = parser.parse_args(argv)
    needed = ("input", "output", "report", "source_unit", "target_unit", "journal")
    if not all(getattr(args, key) is not None for key in needed):
        if any(getattr(args, key) is not None for key in needed):
            parser.error("Conversion requires --input --output --report --source-unit --target-unit --journal")
        print("Bank2Odoo headless conversion CLI. Persian desktop GUI is available separately:\n"
              "  python -m bank2odoo.ui (or Run.bat on Windows).\n"
              "No bank file processed. Use --help for explicit review-candidate conversion command.")
        return 0
    try:
        approved_factor = Decimal(args.approved_factor) if args.approved_factor is not None else None
        result = convert(args.input, Context(args.source_unit, args.target_unit, args.journal,
                                             args.decimal_places, approved_factor))
        save_candidate(result, args.output, args.report)
    except (StatementError, OSError, InvalidOperation) as exc:
        print(f"Conversion NOT completed; no approved Odoo import: {exc}", file=sys.stderr)
        return 1
    print(f"REVIEW CANDIDATE ONLY: {len(result.rows)} {result.bank} transactions; "
          f"balance diagnostic (not accounting approval): {result.balance_status}. CSV and PRIVATE report written. "
          "No Odoo import or journal verification performed.")
    return 0
