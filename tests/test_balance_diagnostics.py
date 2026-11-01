"""Conversion-first balance diagnostics; entirely synthetic source data."""

from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

import xlwt

from bank2odoo.cli import main as cli_main
from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting.output import output_csv, save_candidate
from bank2odoo.validation.financial import StatementError
from test_conversion import MELLI_HEADER, write_melli, write_mellat


def movements():
    return [
        ["4", "1405/07/04", "12:00:00", "واریز", "10", "SYN-4", "",
         "واریز ساختگی", "", "180"],
        ["3", "1405/07/03", "12:00:00", "واریز", "20", "SYN-3", "",
         "اصلاحیه ساختگی", "", "170"],
        ["2", "1405/07/02", "12:00:00", "برداشت", "5", "SYN-2", "",
         "کارمزد ساختگی", "", "95"],
        ["1", "1405/07/01", "12:00:00", "واریز", "5", "SYN-1", "",
         "واریز دیگر", "", "100"],
    ]


class ConversionFirstDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / "fictional.xls"
        self.rows = movements()
        self._write()

    def _write(self):
        write_melli(self.source, self.rows)

    def _convert(self):
        return convert(self.source, Context("IRR", "IRR", "Synthetic Journal"))

    def _save(self, result, name="candidate"):
        csv_path = self.folder / (name + ".csv")
        report_path = self.folder / (name + "_PRIVATE.txt")
        save_candidate(result, csv_path, report_path)
        return csv_path, report_path

    def test_documented_gap_converts_every_observed_movement_with_private_trace(self):
        result = self._convert()
        self.assertEqual(result.ordering, "newest-to-oldest")
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(result.net, Decimal("30"))
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN:"))
        self.assertEqual((result.opening, result.closing), (None, None))
        self.assertIn("source rows 8/9; source-unit residual 55", "\n".join(result.issues))
        expected = ("Date,Label,Amount\n"
                    "2026-09-26,واریز ساختگی,10\n"
                    "2026-09-25,اصلاحیه ساختگی,20\n"
                    "2026-09-24,کارمزد ساختگی,-5\n"
                    "2026-09-23,واریز دیگر,5\n")
        self.assertEqual(output_csv(result), expected)
        csv_path, report_path = self._save(result)
        self.assertEqual(csv_path.read_bytes(), expected.encode("utf-8"))
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("Conversion completed for observed movements", report)
        self.assertIn("REVIEW CANDIDATE ONLY", report)
        self.assertIn("Balance check: NOT_PROVEN", report)
        trace = [json.loads(line) for line in report.splitlines() if line.startswith("{")]
        self.assertEqual([r["source_physical_row"] for r in trace], [7, 8, 9, 10])
        self.assertEqual([r["csv_row"] for r in trace], [2, 3, 4, 5])
        self.assertEqual([r["dest_amount"] for r in trace], ["10", "20", "-5", "5"])
        self.assertTrue(all(len(r["original_columns"]) == len(MELLI_HEADER) for r in trace))

    def test_continuous_four_movements_remain_diagnostic_pass(self):
        self.rows[2][9] = "150"
        self.rows[3][9] = "155"
        self._write()
        result = self._convert()
        self.assertEqual(result.balance_status, "PASS: 3 consecutive balance transitions")
        self.assertEqual(len(result.rows), 4)
        self.assertEqual((result.opening, result.closing), (Decimal("150"), Decimal("180")))

    def test_extra_unexplained_discrepancy_is_reported_not_silenced(self):
        self.rows[0][9] = "181"
        self._write()
        result = self._convert()
        self.assertEqual(len(result.rows), 4)
        self.assertIn("2 balance discontinuity(ies)", result.balance_status)
        issues = "\n".join(result.issues)
        self.assertIn("source rows 7/8", issues)
        self.assertIn("source rows 8/9", issues)
        self.assertEqual((result.opening, result.closing), (None, None))

    def test_invalid_or_missing_optional_balances_keep_original_cells(self):
        self.rows[1][9] = "UNPARSEABLE_BALANCE"
        self.rows[2][9] = ""
        self._write()
        result = self._convert()
        self.assertEqual(len(result.rows), 4)
        self.assertIn("2 missing/unusable balance(s)", result.balance_status)
        self.assertIn("Unparseable optional balance at source row 8", "\n".join(result.issues))
        self.assertEqual((result.opening, result.closing), (None, None))
        _, report_path = self._save(result)
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("UNPARSEABLE_BALANCE", report)
        self.assertIn('"balance_evidence_issue": "Unparseable optional balance at source row 8"', report)

    def test_no_balance_column_is_not_a_schema_failure(self):
        path = self.folder / "no_balance.xls"
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Synthetic")
        for i, header in enumerate(MELLI_HEADER):
            if i != 9:
                sheet.write(5, i, header)
        for r, fields in enumerate(self.rows, start=6):
            for i, value in enumerate(fields):
                if i != 9:
                    sheet.write(r, i, value)
        workbook.save(str(path))
        result = convert(path, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(len(result.rows), 4)
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN:"))
        self.assertEqual(sum(x.balance is None for x in result.rows), 4)

    def test_duplicate_optional_balance_headers_are_diagnostic_only(self):
        path = self.folder / "ambiguous_optional_balance.xls"
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Synthetic")
        for i, header in enumerate(MELLI_HEADER):
            sheet.write(5, i, "مانده" if i == 10 else header)
        for r, fields in enumerate(self.rows, start=6):
            for i, value in enumerate(fields):
                sheet.write(r, i, value)
        workbook.save(str(path))
        result = convert(path, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(len(result.rows), 4)
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN:"))
        self.assertTrue(all(m.balance is None for m in result.rows))
        self.assertTrue(all("Duplicate/ambiguous optional balance headers" in m.balance_issue
                            for m in result.rows))
        csv_path = self.folder / "duplicate_optional.csv"
        report_path = self.folder / "duplicate_optional_PRIVATE.txt"
        save_candidate(result, csv_path, report_path)
        self.assertIn("Duplicate/ambiguous optional balance headers",
                      report_path.read_text(encoding="utf-8"))
        self.assertIn('"source_physical_row": 7', report_path.read_text(encoding="utf-8"))

    def test_same_timestamp_at_gap_boundary_does_not_block_conversion(self):
        self.rows[2][1] = self.rows[1][1]
        self.rows[2][2] = self.rows[1][2]
        self._write()
        result = self._convert()
        self.assertEqual(len(result.rows), 4)
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN"))
        self.assertEqual([m.row.physical_row for m in result.rows], [7, 8, 9, 10])

    def test_essential_fields_still_fail_closed(self):
        for column, invalid in ((1, "1400/12/30"), (3, "نامعلوم"),
                                (4, "0"), (4, "bad decimal"), (7, "")):
            with self.subTest(column=column, invalid=invalid):
                self.rows = movements()
                self.rows[2][column] = invalid
                self._write()
                with self.assertRaises(StatementError):
                    self._convert()
        self.rows = movements()
        self._write()

    def test_cli_success_with_warning_and_financial_safeguards(self):
        output = self.folder / "from_cli.csv"
        report = self.folder / "from_cli_PRIVATE.txt"
        args = ["--input", str(self.source), "--output", str(output),
                "--report", str(report), "--source-unit", "IRR",
                "--target-unit", "IRR", "--journal", "Synthetic Journal"]
        status = StringIO()
        with redirect_stdout(status):
            self.assertEqual(cli_main(args), 0)
        self.assertIn("REVIEW CANDIDATE ONLY", status.getvalue())
        self.assertIn("balance diagnostic", status.getvalue())
        self.assertTrue(output.exists())
        self.assertTrue(report.exists())
        with self.assertRaises(SystemExit) as caught:
            cli_main(["--gap-before-row", "8"])
        self.assertEqual(caught.exception.code, 2)
        other = self.folder / "bad.csv"
        other_report = self.folder / "bad.txt"
        with redirect_stderr(StringIO()):
            self.assertEqual(cli_main(["--input", str(self.source),
                "--output", str(other), "--report", str(other_report),
                "--source-unit", "TOMAN", "--target-unit", "IRR",
                "--journal", "Synthetic Journal"]), 1)
        self.assertFalse(other.exists())
        self.assertFalse(other_report.exists())

    def test_mellat_mismatch_does_not_weaken_amount_or_direction(self):
        path = self.folder / "fictional_mellat.csv"
        records = [
            ["1", "1405/07/01", "10:00:00", "SYN-1", "واریز", "0", "10", "10"],
            ["2", "1405/07/02", "11:00:00", "SYN-2", "کارمزد", "5", "0", "999"],
        ]
        write_mellat(path, records)
        result = convert(path, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(len(result.rows), 2)
        self.assertIn("BALANCE DISCONTINUITY", "\n".join(result.issues))
        self.assertEqual([m.signed for m in result.rows], [Decimal("10"), Decimal("-5")])
        records[1][5] = "7"
        records[1][6] = "2"
        write_mellat(path, records)
        with self.assertRaisesRegex(StatementError, "debit/credit"):
            convert(path, Context("IRR", "IRR", "Synthetic Journal"))


if __name__ == "__main__":
    unittest.main()
