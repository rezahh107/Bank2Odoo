"""Bank2Odoo black-box end-to-end tests with independent synthetic expectations."""

import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import xlwt  # test-only legacy BIFF8 XLS writer, not the production XLS parser

from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting.output import control_report, output_csv, save_candidate
from bank2odoo.validation.financial import StatementError, amount, jalali_date

ROOT = Path(__file__).resolve().parents[1]


MELLI_HEADER = ["ردیف", "تاریخ", "زمان", "نوع", "مبلغ", "شماره پیگیری", "اطلاعات تکمیلی",
                "شرح", "توضیحات", "مانده", "ستون۱۱", "ستون۱۲", "ستون۱۳", "ستون۱۴"]
MELLAT_HEADER = ["رديف", "تاریخ", "زمان", "شماره سریال", "شرح", "مبلغ گردش بدهکار",
                 "مبلغ گردش بستانکار", "مانده", "واریز کننده/ذینفع", "ستون۱۰", "ستون۱۱", "ستون۱۲"]


def write_melli(path: Path, values: list[list[str]], *, broken_header: bool = False) -> None:
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("Synthetic")
    sheet.write(0, 0, "Synthetic bank statement (NOT real bank data)")
    headers = MELLI_HEADER.copy()
    if broken_header:
        headers[3] = "نامعلوم"
    for col, field in enumerate(headers):
        sheet.write(5, col, field)  # intentionally NOT historical row 8
    for r, fields in enumerate(values, start=6):
        for c, value in enumerate(fields):
            sheet.write(r, c, value)
    book.save(str(path))


def write_mellat(path: Path, values: list[list[str]], encoding: str = "utf-8-sig") -> None:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["Synthetic test file, not a real bank statement"])
    writer.writerow(MELLAT_HEADER)
    writer.writerows(values)
    path.write_bytes(stream.getvalue().encode(encoding))


class EngineEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_melli_true_ole_xls_reverse_both_signs_and_associated_fee(self) -> None:
        original = self.root / "legacy.data"  # prove content, not extension
        rows = [
            ["3", "۱۴۰۵/۰۷/۰۳", "09:00:01", "برداشت", "۵", "0009", "", "کارمزد پل", "", "695"],
            ["2", "1405/07/02", "09:00:00", "برداشت", "300", "0009", "", "انتقال پل", "", "700"],
            ["1", "1405/07/01", "09:00:00", "واریز", "1,000", "0003", "", "واریز آزمایشی", "", "1000"],
        ]
        write_melli(original, rows)
        self.assertEqual(original.read_bytes()[:8], bytes.fromhex("D0CF11E0A1B11AE1"))
        result = convert(original, Context("IRR", "IRR", "Synthetic Journal"))
        csv_actual = output_csv(result)
        expected = ("Date,Label,Amount\n"
                    "2026-09-25,کارمزد پل,-5\n"
                    "2026-09-24,انتقال پل,-300\n"
                    "2026-09-23,واریز آزمایشی,1000\n")
        self.assertEqual(csv_actual, expected)
        self.assertEqual(result.balance_status, "PASS: 2 consecutive balance transitions")
        self.assertEqual((result.opening, result.closing, result.net),
                         (Decimal("0"), Decimal("695"), Decimal("695")))
        self.assertEqual([r.row.physical_row for r in result.rows], [7, 8, 9])
        self.assertIn("TENTATIVE shared-reference", control_report(result))
        self.assertIn('"source_physical_row": 7', control_report(result))
        self.assertIn('"source_report_row": "3"', control_report(result))

    def test_mellat_real_cp1256_csv_forward_and_private_report(self) -> None:
        source = self.root / "mellat.binary-looking"  # format determined by actual data
        rows = [
            ["1", "1405/07/01", "10:00:00", "0007", 'واریز آزمایشی', "0", "2000", "2500"],
            ["2", "1405/07/02", "10:00:00", "0008", 'برداشت، آزمایشی', "100", "0", "2400"],
            ["3", "1405/07/03", "10:00:00", "0008", 'کارمزد پل', "10", "0", "2390"],
            ["4", "1405/07/04", "10:00:00", "0008", 'اصلاحیه "نمونه", بدون تایید', "0", "100", "2490"],
        ]
        write_mellat(source, rows, encoding="cp1256")
        result = convert(source, Context("TOMAN", "IRR", "Synthetic Journal", approved_factor=Decimal(10)))
        expected = ("Date,Label,Amount\n"
                    "2026-09-23,واریز آزمایشی,20000\n"
                    "2026-09-24,برداشت، آزمایشی,-1000\n"
                    "2026-09-25,کارمزد پل,-100\n"
                    '2026-09-26,"اصلاحیه ""نمونه"", بدون تایید",1000\n')
        self.assertEqual(output_csv(result), expected)
        self.assertEqual(result.encoding, "cp1256")
        self.assertEqual(result.balance_status, "PASS: 3 consecutive balance transitions")
        self.assertEqual((result.opening, result.closing), (Decimal(500), Decimal(2490)))
        dest, report = self.root / "candidate.csv", self.root / "PRIVATE.txt"
        save_candidate(result, dest, report)
        self.assertEqual(dest.read_text("utf-8"), expected)
        self.assertIn("0007", report.read_text("utf-8"))
        self.assertIn("NOT authorized for live Odoo import", report.read_text("utf-8"))
        self.assertEqual(len(list(csv.reader(StringIO(dest.read_text("utf-8"))))), 5)
        with self.assertRaises(StatementError):
            save_candidate(result, dest, report)

    def test_utf8_arabic_digits_thousands_and_duplicate_preserved(self) -> None:
        source = self.root / "ar.csv"
        rows = [
            ["1", "۱۴۰۵/۰۷/۰۱", "10:00:00", "0001", "کارمزد", "٠", "١٬٠٠٠", "1000"],
            ["2", "1405/07/01", "10:00:00", "0001", "کارمزد", "٠", "١٬٠٠٠", "2000"],
        ]
        write_mellat(source, rows)
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(len(result.rows), 2)
        self.assertIn("POSSIBLE duplicate, retained", '\n'.join(result.issues))
        self.assertIn("NOT_PROVEN", result.balance_status)  # tied timestamps cannot prove order
        self.assertEqual(output_csv(result).count("1000"), 2)

    def test_date_boundaries_and_signed_decimal_normalization(self) -> None:
        self.assertEqual(jalali_date("۱۳۹۹/۱۲/۳۰").isoformat(), "2021-03-20")
        self.assertEqual(jalali_date("۱۴۰۰/۰۱/۰۱").isoformat(), "2021-03-21")
        self.assertEqual(jalali_date("۱۴۰۵/۰۱/۰۱").isoformat(), "2026-03-21")
        with self.assertRaises(StatementError):
            jalali_date("1400/12/30")
        self.assertEqual(amount("-١٬٠٠٠٫٢٥"), Decimal("-1000.25"))
        for value in ("1,00,0", "1.234,55", "NaN", "1e6", "", "10,20"):
            with self.subTest(value=value), self.assertRaises(StatementError):
                amount(value)

    def test_melli_missing_header_and_corrupt_xls_fail(self) -> None:
        source = self.root / "bad.xls"
        write_melli(source, [["1", "1405/07/01", "10:00:00", "واریز", "50", "", "", "نمونه", "", "50"]], broken_header=True)
        with self.assertRaisesRegex(StatementError, "Expected one"):
            convert(source, Context("IRR", "IRR", "S"))
        source.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"bad data")
        with self.assertRaisesRegex(StatementError, "Invalid/unreadable legacy XLS"):
            convert(source, Context("IRR", "IRR", "S"))

    def test_ambiguous_money_dates_and_balance_mismatch_fail_without_files(self) -> None:
        source = self.root / "unsafe.csv"
        template = [
            ["1", "1405/07/01", "10:00:00", "0001", "نمونه", "0", "50", "50"],
            ["2", "1405/07/02", "10:00:00", "0002", "نمونه", "30", "0", "20"],
        ]
        variants = [
            (5, "20", "debit/credit"),
            (1, "1400/12/30", "Impossible Jalali"),
            (7, "21", "balance mismatch"),
            (5, "-30", "debit/credit"),
        ]
        for column, replacement, message in variants:
            with self.subTest(replacement=replacement):
                rows = [r.copy() for r in template]
                rows[1][column] = replacement
                write_mellat(source, rows)
                with self.assertRaisesRegex(StatementError, message):
                    convert(source, Context("IRR", "IRR", "S"))
                self.assertFalse((self.root / "candidate.csv").exists())

    def test_units_precision_no_silent_rounding(self) -> None:
        path = self.root / "precise.csv"
        write_mellat(path, [["1", "1405/07/01", "10:00:00", "1", "نمونه", "0", "1.25", "1.25"]])
        with self.assertRaisesRegex(StatementError, "factor"):
            convert(path, Context("TOMAN", "IRR", "S"))
        with self.assertRaisesRegex(StatementError, "decimal places"):
            convert(path, Context("IRR", "IRR", "S", decimal_places=0))
        result = convert(path, Context("IRR", "IRR", "S", decimal_places=2))
        self.assertIn("1.25", output_csv(result))
        self.assertIn("NOT_PROVEN", result.balance_status)

    def test_cli_real_conversion_and_failure_safe(self) -> None:
        source = self.root / "in.csv"
        write_mellat(source, [["1", "1405/07/01", "10:00:00", "1", "نمونه", "0", "50", "50"]])
        out, report = self.root / "result.csv", self.root / "private.txt"
        base = [sys.executable, "-m", "bank2odoo", "--input", str(source),
                "--output", str(out), "--report", str(report), "--source-unit", "IRR",
                "--target-unit", "IRR", "--journal", "Synthetic Journal"]
        first = subprocess.run(base, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(out.read_text("utf-8"), "Date,Label,Amount\n2026-09-23,نمونه,50\n")
        self.assertTrue(report.exists())
        again = subprocess.run(base, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(again.returncode, 1)
        self.assertIn("not already exist", again.stderr)
        self.assertEqual(out.read_text("utf-8"), "Date,Label,Amount\n2026-09-23,نمونه,50\n")

    def test_atomic_write_rollback_when_second_link_fails(self) -> None:
        from unittest.mock import patch
        source = self.root / "one.csv"
        write_mellat(source, [["1", "1405/07/01", "10:00:00", "1", "نمونه", "0", "50", "50"]])
        result = convert(source, Context("IRR", "IRR", "S"))
        csv_path, report_path = self.root / "out.csv", self.root / "report.txt"
        import bank2odoo.reporting.output as output
        real_link = output.os.link
        calls = 0
        def fail_second(src: Path, dst: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic second-file publish failure")
            real_link(src, dst)
        with patch.object(output.os, "link", side_effect=fail_second), self.assertRaises(OSError):
            save_candidate(result, csv_path, report_path)
        self.assertFalse(csv_path.exists())
        self.assertFalse(report_path.exists())
        self.assertEqual(list(self.root.glob(".bank2odoo-*")), [])


if __name__ == "__main__":
    unittest.main()
