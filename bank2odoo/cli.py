"""Safe status-only entrypoint; no statement processing is currently available."""

import argparse


MESSAGE = (
    "Bank2Odoo foundation only. Bank conversion and the desktop interface "
    "are not implemented. No files were read, converted, or written."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bank2odoo",
        description="Bank2Odoo foundation status (no conversion available).",
    )
    parser.add_argument(
        "--version", action="version", version="Bank2Odoo 0.1.0 (foundation only)"
    )
    parser.parse_args(argv)
    print(MESSAGE)
    return 0
