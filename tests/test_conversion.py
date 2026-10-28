"""Bank2Odoo black-box end-to-end tests with independent synthetic expectations."""

import csv
import json
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
    text = stream.getvalue()
    if encoding == "cp1256":
        # Genuine Windows Arabic encoding has U+064A, not Persian U+06CC.
        # Do not replace undecodable bytes: produce an actually encodable sample.
        text = text.replace("ی", "ي").replace("ک", "ك")
        text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    path.write_bytes(text.encode(encoding))


class EngineEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_28_digit_credits_do_not_round_in_aggregate_or_report(self) -> None:
        # Expected 29-digit total is a literal independent of Decimal arithmetic.
        single = "9999999999999999999999999999"
        exact_total = "19999999999999999999999999998"
        source = self.root / "precision_mellat.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "001", "واریز یک", "0", single, single],
            ["2", "1405/07/02", "11:00:00", "002", "واریز دو", "0", single, exact_total],
        ])
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(result.credit_total, Decimal(exact_total))
        self.assertEqual(result.net, Decimal(exact_total))
        self.assertEqual(result.opening, Decimal("0"))
        self.assertEqual(result.closing, Decimal(exact_total))
        self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
        expected_csv = ("Date,Label,Amount\n"
                        f"2026-09-23,واریز یک,{single}\n"
                        f"2026-09-24,واریز دو,{single}\n")
        self.assertEqual(output_csv(result), expected_csv)
        report = control_report(result)
        self.assertIn(f"credit total: {exact_total}; net: {exact_total}", report)
        self.assertIn(f"Converted net (IRR): {exact_total}", report)

    def test_large_debits_cancellation_and_balance_transitions(self) -> None:
        single = "9999999999999999999999999999"
        exact_total = "19999999999999999999999999999"
        source = self.root / "synthetic_cancellation.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "101", "واریز", "0", single, single],
            ["2", "1405/07/02", "10:00:00", "102", "برداشت", single, "0", "0"],
            ["3", "1405/07/03", "10:00:00", "103", "کارمزد", single, "0", "-" + single],
            ["4", "1405/07/04", "10:00:00", "104", "اصلاح", "0", single, "0"],
            ["5", "1405/07/05", "10:00:00", "105", "واریز", "0", "1", "1"],
            ["6", "1405/07/06", "10:00:00", "106", "برداشت", "1", "0", "0"],
        ])
        from decimal import localcontext
        with localcontext() as decimal_ctx:
            decimal_ctx.prec = 3  # External context must never affect money.
            result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
            report = control_report(result)
        self.assertEqual(result.debit_total, Decimal(exact_total))
        self.assertEqual(result.credit_total, Decimal(exact_total))
        self.assertEqual(result.net, Decimal("0"))
        self.assertEqual((result.opening, result.closing), (Decimal("0"), Decimal("0")))
        self.assertEqual(result.balance_status, "PASS: 5 consecutive balance transitions")
        self.assertIn("Converted net (IRR): 0", report)
        self.assertEqual(len(result.rows), 6)
        self.assertIn(f"2026-09-25,کارمزد,-{single}\n", output_csv(result))

    def test_large_factor_scaling_and_control_report_are_exact(self) -> None:
        single = "9999999999999999999999999999"
        source_total = "19999999999999999999999999998"
        scaled_single = "99999999999999999999999999990"
        scaled_total = "199999999999999999999999999980"
        source = self.root / "synthetic_units.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "110", "نمونه یک", "0", single, single],
            ["2", "1405/07/02", "10:00:00", "111", "نمونه دو", "0", single, source_total],
        ])
        result = convert(source, Context("TOMAN", "IRR", "Synthetic Journal",
                                         approved_factor=Decimal("10")))
        self.assertEqual(result.credit_total, Decimal(source_total))
        self.assertEqual([format(x.converted, "f") for x in result.rows],
                         [scaled_single, scaled_single])
        self.assertEqual(
            output_csv(result),
            "Date,Label,Amount\n"
            f"2026-09-23,نمونه یک,{scaled_single}\n"
            f"2026-09-24,نمونه دو,{scaled_single}\n",
        )
        self.assertIn(f"Converted net (IRR): {scaled_total}", control_report(result))

    def test_large_melli_reverse_balance_and_conflict_detection(self) -> None:
        single = "9999999999999999999999999999"
        source = self.root / "synthetic_melli.xls"
        rows = [
            ["2", "1405/07/02", "10:00:00", "برداشت", single, "004", "",
             "کارمزد آزمایشی", "", "0"],
            ["1", "1405/07/01", "10:00:00", "واریز", single, "005", "",
             "اصلاحیه آزمایشی", "", single],
        ]
        write_melli(source, rows)
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(result.net, Decimal("0"))
        self.assertEqual((result.opening, result.closing), (Decimal("0"), Decimal("0")))
        self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
        self.assertIn(f"2026-09-24,کارمزد آزمایشی,-{single}", output_csv(result))
        rows[0][9] = "1"  # Exact arithmetic must detect a one-unit mismatch.
        write_melli(source, rows)
        with self.assertRaisesRegex(StatementError, "balance mismatch"):
            convert(source, Context("IRR", "IRR", "Synthetic Journal"))

    def test_low_context_melli_signed_value_and_inverse_unit_factor(self) -> None:
        from decimal import localcontext
        huge = "99999999999999999999999999999999"
        source = self.root / "synthetic_large_melli.xls"
        write_melli(source, [
            ["2", "1405/07/02", "10:00:00", "برداشت", huge, "100",
             "", "برداشت بزرگ", "", "0"],
            ["1", "1405/07/01", "10:00:00", "واریز", huge, "101",
             "", "واریز بزرگ", "", huge],
        ])
        with localcontext() as ctx:
            ctx.prec = 2
            result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
            private_report = control_report(result)
        self.assertEqual(result.rows[0].signed, Decimal("-" + huge))
        self.assertEqual(result.rows[1].signed, Decimal(huge))
        self.assertEqual(result.debit_total, Decimal(huge))
        self.assertEqual(result.credit_total, Decimal(huge))
        self.assertEqual(result.net, Decimal("0"))
        self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
        self.assertIn("Converted net (IRR): 0", private_report)

        # The inverse approved unit direction must also preserve every digit.
        from bank2odoo.validation.financial import exact_scaled
        source_amount = Decimal("99999999999999999999999999999990")
        expected = Decimal("9999999999999999999999999999999")
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(exact_scaled(source_amount, Decimal("0.1"), 0), expected)

    def test_unicode_label_controls_preserve_persian_and_private_source_trace(self) -> None:
        # This crosses the real Mellat parser, core, CSV writer and atomic save.
        first = 'پرداخت\u200cیار، Visa "A"'
        second = "کارمزد\u200b\u2066 پل\nمرحله\x07نهایی"
        source = self.root / "synthetic_unicode_mellat.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "0001", first, "0", "100", "100"],
            ["2", "1405/07/02", "11:00:00", "0002", second, "5", "0", "95"],
        ])
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        csv_path, report_path = self.root / "unicode.csv", self.root / "unicode_private.txt"
        save_candidate(result, csv_path, report_path)
        expected = (
            'Date,Label,Amount\n'
            '2026-09-23,"پرداخت\u200cیار، Visa ""A""",100\n'
            '2026-09-24,کارمزد پل مرحله نهایی,-5\n'
        )
        self.assertEqual(csv_path.read_bytes(), expected.encode("utf-8"))
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
        self.assertEqual((result.debit_total, result.credit_total, result.net),
                         (Decimal("5"), Decimal("100"), Decimal("95")))
        traces = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()
                  if line.startswith("{")]
        self.assertEqual(len(traces), 2)
        self.assertEqual([x["csv_row"] for x in traces], [2, 3])
        self.assertEqual(traces[0]["original_columns"]["شرح [5]"], first)
        self.assertEqual(traces[1]["original_columns"]["شرح [5]"], second)
        self.assertEqual(traces[1]["dest_label"], "کارمزد پل مرحله نهایی")

    def test_only_invisible_unicode_description_is_rejected(self) -> None:
        # A visually empty description must not reach an accountant's CSV.
        source = self.root / "synthetic_invisible_mellat.csv"
        destination = self.root / "not_created.csv"
        private = self.root / "not_created_private.txt"
        for description in ("\u200b\u2066\u2069\u200c\u200d\u202e", "\u200c"):
            with self.subTest(description=ascii(description)):
                write_mellat(source, [
                    ["1", "1405/07/01", "10:00:00", "0001",
                     description, "0", "100", "100"],
                ])
                with self.assertRaisesRegex(StatementError, "Missing meaningful bank description"):
                    result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
                    save_candidate(result, destination, private)
                self.assertFalse(destination.exists())
                self.assertFalse(private.exists())

    def test_destination_precision_is_recorded_without_rounding(self) -> None:
        source = self.root / "synthetic_report_precision.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "0001", "واریز آزمایشی",
             "0", "1.25", "1.25"],
            ["2", "1405/07/02", "11:00:00", "0002", "کارمزد آزمایشی",
             "0.25", "0", "1.00"],
        ])
        context = Context("IRR", "IRR", "Synthetic Journal", decimal_places=2)
        result = convert(source, context)
        csv_path = self.root / "precision.csv"
        private = self.root / "precision_private.txt"
        save_candidate(result, csv_path, private)
        self.assertEqual(result.decimal_places, 2)
        report = private.read_text(encoding="utf-8")
        self.assertIn("Destination decimal precision (user-confirmed; Odoo-unverified): 2", report)
        self.assertIn("Source unit: IRR; target unit: IRR; approved factor: 1", report)
        self.assertIn("Journal (user-entered, UNVERIFIED): Synthetic Journal", report)
        self.assertEqual(csv_path.read_bytes(), (
            "Date,Label,Amount\n"
            "2026-09-23,واریز آزمایشی,1.25\n"
            "2026-09-24,کارمزد آزمایشی,-0.25\n"
        ).encode("utf-8"))
        with self.assertRaisesRegex(StatementError, "decimal places"):
            convert(source, Context("IRR", "IRR", "Synthetic Journal", decimal_places=0))

    def test_fractional_precision_and_unit_factor_boundaries(self) -> None:
        source = self.root / "synthetic_decimals.csv"
        large = "9999999999999999999999999999.01"
        expected_total = "19999999999999999999999999998.02"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "1", "آزمایش", "0", large, large],
            ["2", "1405/07/02", "10:00:00", "2", "آزمایش", "0", large, expected_total],
        ])
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal", decimal_places=2))
        self.assertEqual(result.credit_total, Decimal(expected_total))
        self.assertEqual(result.net, Decimal(expected_total))
        self.assertIn(expected_total, control_report(result))
        self.assertIn(f"2026-09-24,آزمایش,{large}\n", output_csv(result))
        with self.assertRaisesRegex(StatementError, "decimal places"):
            convert(source, Context("IRR", "IRR", "Synthetic Journal", decimal_places=0))

        from bank2odoo.validation.financial import exact_add, exact_scaled, exact_sub, exact_sum
        self.assertEqual(exact_sub(Decimal("1"), Decimal("0.0000000000000000000000000001")),
                         Decimal("0.9999999999999999999999999999"))
        self.assertEqual(exact_add(Decimal("1e28"), Decimal("1")), Decimal("10000000000000000000000000001"))
        self.assertEqual(exact_sum((Decimal("1e28"), Decimal("-1e28"), Decimal("0.01"))),
                         Decimal("0.01"))
        self.assertEqual(exact_scaled(Decimal("10.000"), Decimal("0.1"), 0), Decimal("1"))
        with self.assertRaisesRegex(StatementError, "decimal places"):
            exact_scaled(Decimal("1"), Decimal("0.1"), 0)
        with self.assertRaisesRegex(StatementError, "Cannot represent"):
            exact_add(Decimal("1e+999999999999999999"), Decimal("1"))

    def test_melli_true_ole_xls_reverse_both_signs_and_associated_fee(self) -> None:
        original = self.root / "legacy.data"  # prove content, not extension
        rows = [
            ["3", "۱۴۰۵/۰۷/۰۲", "09:00:01", "برداشت", "۵", "0009", "", "کارمزد پل", "", "695"],
            ["2", "1405/07/02", "09:00:00", "برداشت", "300", "0009", "", "انتقال پل", "", "700"],
            ["1", "1405/07/01", "09:00:00", "واریز", "1,000", "0003", "", "واریز آزمایشی", "", "1000"],
        ]
        write_melli(original, rows)
        self.assertEqual(original.read_bytes()[:8], bytes.fromhex("D0CF11E0A1B11AE1"))
        result = convert(original, Context("IRR", "IRR", "Synthetic Journal"))
        csv_actual = output_csv(result)
        expected = ("Date,Label,Amount\n"
                    "2026-09-24,کارمزد پل,-5\n"
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
            ["1", "1405/07/01", "10:00:00", "0007", 'واریز نمونه', "0", "2000", "2500"],
            ["2", "1405/07/02", "10:00:00", "0008", 'برداشت، نمونه', "100", "0", "2400"],
            ["3", "1405/07/03", "10:00:00", "0008", 'کارمزد پل', "10", "0", "2390"],
            ["4", "1405/07/04", "10:00:00", "0008", 'اصلاح "نمونه", دوباره', "0", "100", "2490"],
        ]
        write_mellat(source, rows, encoding="cp1256")
        result = convert(source, Context("TOMAN", "IRR", "Synthetic Journal", approved_factor=Decimal(10)))
        expected = ("Date,Label,Amount\n"
                    "2026-09-23,واریز نمونه,20000\n"
                    "2026-09-24,برداشت، نمونه,-1000\n"
                    "2026-09-25,کارمزد پل,-100\n"
                    '2026-09-26,"اصلاح ""نمونه"", دوباره",1000\n')
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

    def test_footer_prefix_does_not_hide_final_melli_movement(self) -> None:
        # Newest first: dropping oldest row still leaves a valid-looking
        # 1-transition chain among the two retained movements.
        source = self.root / "melli_footer_bypass.xls"
        write_melli(source, [
            ["3", "1405/07/03", "11:00:00", "واریز", "15", "FICT-3",
             "", "واریز آخر ساختگی", "", "145"],
            ["2", "1405/07/02", "10:00:00", "برداشت", "20", "FICT-2",
             "", "برداشت ساختگی", "", "130"],
            ["جمع کل 1", "1405/07/01", "09:00:00", "واریز", "50", "FICT-1",
             "", "واریز پنهان ساختگی", "", "150"],
        ])
        try:
            result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        except StatementError as exc:
            self.assertRegex(str(exc), "Ambiguous financial-bearing footer")
        else:
            self.fail(
                "Melli silently omitted final financial movement: "
                f"source=3, output={len(result.rows)}, "
                f"balance={result.balance_status}, net={result.net}"
            )
        self.assertFalse((self.root / "melli_candidate.csv").exists())

    def test_footer_prefix_does_not_hide_final_mellat_movement(self) -> None:
        # Oldest first: omitting latest movement can also leave a false
        # positive 1-transition balance check on the retained prefix.
        source = self.root / "mellat_footer_bypass.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "09:00:00", "0001", "واریز ساختگی",
             "0", "50", "150"],
            ["2", "1405/07/02", "10:00:00", "0002", "برداشت ساختگی",
             "20", "0", "130"],
            ["مجموع 3", "1405/07/03", "11:00:00", "0003", "واریز پنهان ساختگی",
             "0", "15", "145"],
        ])
        try:
            result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        except StatementError as exc:
            self.assertRegex(str(exc), "Ambiguous financial-bearing footer")
        else:
            self.fail(
                "Mellat silently omitted final financial movement: "
                f"source=3, output={len(result.rows)}, "
                f"balance={result.balance_status}, net={result.net}"
            )
        self.assertFalse((self.root / "mellat_candidate.csv").exists())

    def test_recognized_pure_footers_remain_supported_for_both_banks(self) -> None:
        melli = self.root / "melli_pure_footer.xls"
        write_melli(melli, [
            ["2", "1405/07/02", "10:00:00", "برداشت", "20", "FICT-2",
             "", "برداشت ساختگی", "", "130"],
            ["1", "1405/07/01", "09:00:00", "واریز", "50", "FICT-1",
             "", "واریز ساختگی", "", "150"],
            ["پایان گزارش آزمایشی"],
        ])
        mellat = self.root / "mellat_pure_footer.csv"
        write_mellat(mellat, [
            ["1", "1405/07/01", "09:00:00", "0001", "واریز ساختگی",
             "0", "50", "150"],
            ["2", "1405/07/02", "10:00:00", "0002", "برداشت ساختگی",
             "20", "0", "130"],
            ["جمع کل"],
        ])
        for bank, source in (("melli", melli), ("mellat", mellat)):
            with self.subTest(bank=bank):
                result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
                self.assertEqual(len(result.rows), 2)
                self.assertEqual(result.balance_status, "PASS: 1 consecutive balance transitions")
                self.assertEqual(result.net, Decimal("30"))
                self.assertEqual((result.opening, result.closing),
                                 (Decimal("100"), Decimal("130")))

    def test_footer_summary_with_other_populated_cells_requires_review(self) -> None:
        # A recognizable title plus apparent totals is not a *pure* marker.
        # Reject it instead of classifying monetary values as ignorable text.
        melli = self.root / "melli_ambiguous_summary.xls"
        write_melli(melli, [
            ["2", "1405/07/02", "10:00:00", "برداشت", "20", "FICT-2",
             "", "برداشت ساختگی", "", "130"],
            ["1", "1405/07/01", "09:00:00", "واریز", "50", "FICT-1",
             "", "واریز ساختگی", "", "150"],
            ["مجموع گردش", "", "", "", "70", "", "", "", "", ""],
        ])
        mellat = self.root / "mellat_ambiguous_summary.csv"
        write_mellat(mellat, [
            ["1", "1405/07/01", "09:00:00", "0001", "واریز ساختگی",
             "0", "50", "150"],
            ["2", "1405/07/02", "10:00:00", "0002", "برداشت ساختگی",
             "20", "0", "130"],
            ["جمع کل", "", "", "", "", "20", "50", ""],
        ])
        for bank, source in (("melli", melli), ("mellat", mellat)):
            with self.subTest(bank=bank):
                with self.assertRaisesRegex(StatementError, "Ambiguous financial-bearing footer"):
                    convert(source, Context("IRR", "IRR", "Synthetic Journal"))

    def test_transactions_after_a_pure_footer_fail_for_both_banks(self) -> None:
        melli = self.root / "melli_after_footer.xls"
        write_melli(melli, [
            ["2", "1405/07/02", "10:00:00", "برداشت", "20", "FICT-2",
             "", "برداشت ساختگی", "", "130"],
            ["1", "1405/07/01", "09:00:00", "واریز", "50", "FICT-1",
             "", "واریز ساختگی", "", "150"],
            ["پایان گزارش آزمایشی"],
            ["4", "1405/07/03", "11:00:00", "واریز", "15", "FICT-4",
             "", "داده بعد از Footer", "", "145"],
        ])
        mellat = self.root / "mellat_after_footer.csv"
        write_mellat(mellat, [
            ["1", "1405/07/01", "09:00:00", "0001", "واریز ساختگی",
             "0", "50", "150"],
            ["2", "1405/07/02", "10:00:00", "0002", "برداشت ساختگی",
             "20", "0", "130"],
            ["جمع کل"],
            ["4", "1405/07/03", "11:00:00", "0004", "داده بعد از Footer",
             "0", "15", "145"],
        ])
        for bank, source in (("melli", melli), ("mellat", mellat)):
            with self.subTest(bank=bank):
                with self.assertRaisesRegex(StatementError, "Unexpected data after total/footer"):
                    convert(source, Context("IRR", "IRR", "Synthetic Journal"))

    def test_unknown_melli_footer_remains_a_hard_error(self) -> None:
        # The Phase 2 fixture's explicit 'پایان گزارش' marker is supported,
        # but an arbitrary data-bearing row is never silently skipped.
        source = self.root / "unrecognized_footer.xls"
        write_melli(source, [
            ["1", "1405/07/01", "10:00:00", "واریز", "50", "TEST-001",
             "", "واریز ساختگی", "", "50"],
            ["گزارش نامشخص", "", "", "", "", "", "", "", "", ""],
        ])
        with self.assertRaisesRegex(StatementError, "unidentified footer"):
            convert(source, Context("IRR", "IRR", "Synthetic Journal"))

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
            (6, "20", "debit/credit"),
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

    def test_report_producing_version_matches_metadata_and_cli(self) -> None:
        import tomllib
        from bank2odoo.cli import VERSION

        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(VERSION, metadata["project"]["version"])
        cli = subprocess.run([sys.executable, "-m", "bank2odoo", "--version"],
                             cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn(f"Bank2Odoo {VERSION} (headless candidate engine)", cli.stdout)

        source = self.root / "version_fictional.csv"
        write_mellat(source, [
            ["1", "1405/07/01", "10:00:00", "001", "واریز فرضی",
             "0", "50", "50"],
        ])
        result = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        version_line = f"Producing application version: Bank2Odoo {VERSION}"
        self.assertIn(version_line + "\n", control_report(result))
        output_path = self.root / "version_candidate.csv"
        report_path = self.root / "version_control.txt"
        save_candidate(result, output_path, report_path)
        self.assertIn(version_line + "\n", report_path.read_text(encoding="utf-8"))
        self.assertEqual(output_path.read_text(encoding="utf-8"),
                         "Date,Label,Amount\n2026-09-23,واریز فرضی,50\n")

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

    def test_private_output_boundary_rejects_public_checkout(self) -> None:
        source = self.root / "one.csv"
        write_mellat(source, [["1", "1405/07/01", "10:00:00", "1", "نمونه", "0", "50", "50"]])
        result = convert(source, Context("IRR", "IRR", "S"))
        with self.assertRaisesRegex(StatementError, "outside the public source checkout"):
            save_candidate(result, ROOT / "synthetic_candidate.csv", ROOT / "synthetic_control.txt")
        self.assertFalse((ROOT / "synthetic_candidate.csv").exists())
        self.assertFalse((ROOT / "synthetic_control.txt").exists())

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