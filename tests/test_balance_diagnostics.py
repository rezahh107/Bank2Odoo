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

    def test_optional_time_values_keep_both_banks_csv_and_trace(self):
        # The conversion columns do not contain time; raw decoded time is
        # preserved privately, including whitespace for XLS and CSV.
        melli = movements()
        mellat = [
            ["1", "1405/07/01", "10:00:00", "SYN-1", "واریز ساختگی", "0", "10", "10"],
            ["2", "1405/07/02", "11:00:00", "SYN-2", "کارمزد ساختگی", "5", "0", "5"],
        ]
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                baseline = self.folder / ("baseline_" + bank + (".xls" if bank == "melli" else ".csv"))
                changed = self.folder / ("changed_" + bank + (".xls" if bank == "melli" else ".csv"))
                writer = write_melli if bank == "melli" else write_mellat
                original = melli if bank == "melli" else mellat
                writer(baseline, original)
                expected = output_csv(convert(baseline, Context("IRR", "IRR", "Synthetic Journal")))
                for name, value, malformed in (
                    ("valid", "11:03:02", False),
                    ("missing", "", False),
                    ("malformed", " not-a-clock ", True),
                    ("impossible", "25:61:99", True),
                ):
                    with self.subTest(kind=name):
                        records = [row.copy() for row in original]
                        records[1][2] = value
                        writer(changed, records)
                        converted = convert(changed, Context("IRR", "IRR", "Synthetic Journal"))
                        self.assertEqual(output_csv(converted), expected)
                        self.assertEqual(len(converted.rows), len(original))
                        self.assertEqual([m.row.physical_row for m in converted.rows],
                                         list(range(7, 7 + len(original))) if bank == "melli"
                                         else list(range(3, 3 + len(original))))
                        self.assertEqual(converted.rows[1].time_issue is not None, malformed)
                        if malformed:
                            self.assertIsNone(converted.rows[1].time)
                            self.assertIn("Unparseable optional transaction time",
                                          "\n".join(converted.issues))
                        csv_path, report_path = self._save(converted, bank + "_" + name)
                        trace = [json.loads(line) for line in report_path.read_text("utf-8").splitlines()
                                 if line.startswith("{")]
                        self.assertEqual(trace[1]["source_time_raw"], value)
                        self.assertEqual(trace[1]["source_time"], value.strip())
                        self.assertEqual(trace[1]["time_evidence_issue"] is not None, malformed)
                        self.assertEqual([row["csv_row"] for row in trace],
                                         list(range(2, 2 + len(original))))
                        self.assertIn("REVIEW CANDIDATE ONLY",
                                      report_path.read_text("utf-8"))
                        self.assertEqual(csv_path.read_text("utf-8"), expected)

    def test_mixed_and_same_date_unusable_times_deny_order_certainty(self):
        self.rows[1][1] = self.rows[0][1]
        self.rows[1][2] = "malformed"
        self.rows[2][2] = ""
        self._write()
        result = self._convert()
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(result.ordering, "unknown")
        self.assertIn("NOT_PROVEN: incomplete time/order", result.balance_status)
        self.assertIn("Unparseable optional transaction time at source row 8",
                      "\n".join(result.issues))
        self.assertEqual([m.row.physical_row for m in result.rows], [7, 8, 9, 10])

    def test_duplicate_with_unknown_time_remains_possible_and_retained(self):
        records = [
            ["1", "1405/07/01", "unparseable", "SYN", "هزینه ساختگی", "5", "0", "10"],
            ["2", "1405/07/01", "invalid", "SYN", "هزینه ساختگی", "5", "0", "5"],
        ]
        path = self.folder / "possible_duplicates.csv"
        write_mellat(path, records)
        converted = convert(path, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(len(converted.rows), 2)
        self.assertEqual([m.time for m in converted.rows], [None, None])
        self.assertIn("POSSIBLE duplicate, retained", "\n".join(converted.issues))
        self.assertIn("NOT_PROVEN", converted.balance_status)

    def test_unmapped_source_cells_fail_closed_without_index_error(self):
        # A populated cell outside named headers cannot be admitted only
        # because essential fields happen to remain parseable.
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                records = [row.copy() for row in (
                    movements() if bank == "melli" else [
                        ["1", "1405/07/01", "10:00:00", "S1", "واریز", "0", "10", "10"],
                        ["2", "1405/07/02", "11:00:00", "S2", "برداشت", "5", "0", "5"],
                    ]
                )]
                header_width = len(MELLI_HEADER) if bank == "melli" else 12
                records[0].extend([""] * (header_width - len(records[0])))
                records[0].append("EXTRA_SYNTHETIC_CELL")
                path = self.folder / ("extra_" + bank + (".xls" if bank == "melli" else ".csv"))
                (write_melli if bank == "melli" else write_mellat)(path, records)
                original_bytes = path.read_bytes()
                with self.assertRaisesRegex(
                    StatementError, "Unmapped source column or populated unnamed field"
                ) as observed:
                    convert(path, Context("IRR", "IRR", "Synthetic Journal"))
                self.assertIn("Synthetic:7" if bank == "melli" else "CSV:3",
                              str(observed.exception))
                self.assertEqual(path.read_bytes(), original_bytes)
                self.assertFalse((self.folder / (bank + "_candidate.csv")).exists())

    def test_populated_named_trailing_fields_remain_convertible(self):
        # Both supported formats have named supplemental columns outside
        # the essential financial mapping; these are NOT an extra row cell.
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                records = [row.copy() for row in (
                    movements() if bank == "melli" else [
                        ["1", "1405/07/01", "10:00:00", "S1", "واریز", "0", "10", "10"],
                        ["2", "1405/07/02", "11:00:00", "S2", "برداشت", "5", "0", "5"],
                    ]
                )]
                width = len(MELLI_HEADER) if bank == "melli" else 12
                records[0].extend([""] * (width - len(records[0]) - 1))
                records[0].append("NAMED_EXTRA_SYNTH")
                source = self.folder / ("named_trailing_" + bank + (".xls" if bank == "melli" else ".csv"))
                (write_melli if bank == "melli" else write_mellat)(source, records)
                converted = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
                self.assertEqual(len(converted.rows), len(records))
                self.assertEqual([row.row.physical_row for row in converted.rows],
                                 list(range(7, 7 + len(records))) if bank == "melli"
                                 else list(range(3, 3 + len(records))))
                self.assertIn("NAMED_EXTRA_SYNTH", converted.rows[0].row.original.values())
                csv_path = self.folder / ("named_trailing_" + bank + "_candidate.csv")
                report_path = self.folder / ("named_trailing_" + bank + "_PRIVATE.txt")
                save_candidate(converted, csv_path, report_path)
                trace = [json.loads(line) for line in report_path.read_text("utf-8").splitlines()
                         if line.startswith("{")]
                self.assertIn("NAMED_EXTRA_SYNTH", trace[0]["original_columns"].values())
                self.assertEqual(len(trace), len(records))
                self.assertEqual(csv_path.read_text("utf-8"), output_csv(converted))

    def test_mellat_inserted_cell_cannot_change_credit_to_debit(self):
        # Source-width anomaly: a legitimate +900 source credit is shifted
        # into a parseable -700 debit. Both time and balance diagnostics alone
        # are insufficient to prevent a financially incorrect candidate.
        original = [
            ["1", "1405/07/01", "10:00:00", "SYN-1", "ورودی ساختگی", "0", "100", "100"],
            ["2", "1405/07/02", "11:00:00", "321", "700", "0", "900", "1000"],
        ]
        # The bank CSV has twelve documented columns, including named
        # supplemental columns. The final populated cell makes a genuine
        # thirteenth field observable after insertion.
        original = [r + ["", "", "", "TRAIL_SYNTH"] for r in original]
        baseline = self.folder / "mellat_baseline.csv"
        write_mellat(baseline, original)
        accepted = convert(baseline, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual([m.signed for m in accepted.rows],
                         [Decimal("100"), Decimal("900")])
        malformed = [r.copy() for r in original]
        malformed[1].insert(2, "NOT_TIME")
        self.assertEqual(len(malformed[1]), 13)
        source = self.folder / "mellat_inserted.csv"
        write_mellat(source, malformed)
        try:
            altered = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        except StatementError as exc:
            self.assertRegex(str(exc), "Unmapped source column or populated unnamed field")
        else:
            candidate = self.folder / "mellat_shifted.csv"
            private = self.folder / "mellat_shifted_PRIVATE.txt"
            save_candidate(altered, candidate, private)
            trace = [json.loads(line) for line in private.read_text("utf-8").splitlines()
                     if line.startswith("{")]
            self.fail(
                "Financial alignment bypass: intended signed +900, observed "
                + str(altered.rows[1].signed)
                + "; candidate_saved=" + str(candidate.exists())
                + "; csv=" + repr(output_csv(altered))
                + "; warnings=" + repr(altered.issues)
                + "; raw_report_row=" + repr(trace[1]["source_report_row"])
                + "; source_cells=" + str(len(trace[1]["original_columns"]))
            )

    def test_mellat_inserted_cell_with_empty_surplus_still_fails_closed(self):
        # The source's final supplemental field is empty. After insertion
        # the thirteenth cell is also empty; the row-width mismatch remains
        # evidence even though a populated-extra-only check would miss it.
        original = [
            ["1", "1405/07/01", "10:00:00", "SYN-1", "ورودی ساختگی", "0", "100", "100"],
            ["2", "1405/07/02", "11:00:00", "321", "700", "0", "900", "1000"],
        ]
        original = [row + ["", "", "", ""] for row in original]
        baseline = self.folder / "mellat_empty_tail_original.csv"
        write_mellat(baseline, original)
        converted = convert(baseline, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual(converted.rows[1].signed, Decimal("900"))
        shifted = [row.copy() for row in original]
        shifted[1].insert(2, "MALFORMED_TIME")
        self.assertEqual(len(shifted[1]), 13)
        candidate = self.folder / "mellat_empty_tail_candidate.csv"
        private = self.folder / "mellat_empty_tail_PRIVATE.txt"
        source = self.folder / "mellat_empty_tail_shift.csv"
        write_mellat(source, shifted)
        with self.assertRaisesRegex(StatementError, "Unmapped source column or populated unnamed field"):
            convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertFalse(candidate.exists())
        self.assertFalse(private.exists())

    def test_melli_inserted_amount_cell_cannot_change_credit(self):
        # A typed numerical cell inserted in front of the amount may be
        # mistaken for the actual transfer, even while the raw extra XLS
        # column is detected and the description stays syntactically valid.
        rows = [
            ["2", "1405/07/02", "11:00:00", "واریز", "900", "SYN-REF",
             "123", "شرح ساختگی", "", "1000", "", "", "", "TRAIL_SYNTH"],
            ["1", "1405/07/01", "10:00:00", "واریز", "100", "SYN-1",
             "", "واریز ساختگی", "", "100", "", "", "", ""],
        ]
        baseline = self.folder / "melli_original.xls"
        write_melli(baseline, rows)
        accepted = convert(baseline, Context("IRR", "IRR", "Synthetic Journal"))
        self.assertEqual([m.signed for m in accepted.rows],
                         [Decimal("900"), Decimal("100")])
        malformed = [r.copy() for r in rows]
        malformed[0].insert(4, "700")
        source = self.folder / "melli_inserted.xls"
        write_melli(source, malformed)
        try:
            altered = convert(source, Context("IRR", "IRR", "Synthetic Journal"))
        except StatementError as exc:
            self.assertRegex(str(exc), "Unmapped source column or populated unnamed field")
        else:
            candidate = self.folder / "melli_shifted.csv"
            private = self.folder / "melli_shifted_PRIVATE.txt"
            save_candidate(altered, candidate, private)
            self.fail(
                "Financial alignment bypass: intended signed +900, observed "
                + str(altered.rows[0].signed)
                + "; candidate_saved=" + str(candidate.exists())
                + "; csv=" + repr(output_csv(altered))
                + "; warnings=" + repr(altered.issues)
            )

    def test_missing_essential_source_cell_still_fails_closed(self):
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                records = [row.copy() for row in (
                    movements() if bank == "melli" else [
                        ["1", "1405/07/01", "10:00:00", "S1", "واریز", "0", "10", "10"],
                        ["2", "1405/07/02", "11:00:00", "S2", "برداشت", "5", "0", "5"],
                    ]
                )]
                records[0][1] = ""  # Necessary date absent, not optional time.
                path = self.folder / ("missing_date_" + bank + (".xls" if bank == "melli" else ".csv"))
                (write_melli if bank == "melli" else write_mellat)(path, records)
                with self.assertRaises(StatementError):
                    convert(path, Context("IRR", "IRR", "Synthetic Journal"))

    def test_reordered_optional_columns_follow_header_not_position(self):
        # Swap timestamp and reference in both header and each row. Mapping
        # by header must preserve conversion, original timestamp and identity.
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                records = [r.copy() for r in (
                    movements() if bank == "melli" else [
                        ["1", "1405/07/01", "10:00:00", "S1", "واریز", "0", "10", "10"],
                        ["2", "1405/07/02", "11:00:00", "S2", "برداشت", "5", "0", "5"],
                    ]
                )]
                path = self.folder / ("reorder_" + bank + (".xls" if bank == "melli" else ".csv"))
                if bank == "melli":
                    book = xlwt.Workbook()
                    sheet = book.add_sheet("Synthetic")
                    headers = MELLI_HEADER.copy()
                    headers[2], headers[5] = headers[5], headers[2]
                    for i, title in enumerate(headers):
                        sheet.write(5, i, title)
                    for i, row in enumerate(records, 6):
                        row[2], row[5] = row[5], row[2]
                        for j, value in enumerate(row):
                            sheet.write(i, j, value)
                    book.save(str(path))
                    expected_times = ["12:00:00"] * 4
                else:
                    # CSV fixture uses the existing serializer, then exchanges
                    # its header and source cells with the same movement count.
                    import csv
                    with path.open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(["Synthetic only"])
                        headers = ["رديف", "تاریخ", "زمان", "شماره سریال", "شرح",
                                   "مبلغ گردش بدهکار", "مبلغ گردش بستانکار", "مانده"]
                        headers[2], headers[3] = headers[3], headers[2]
                        writer.writerow(headers)
                        for row in records:
                            row[2], row[3] = row[3], row[2]
                            writer.writerow(row)
                    expected_times = ["10:00:00", "11:00:00"]
                result = convert(path, Context("IRR", "IRR", "Synthetic Journal"))
                self.assertEqual(len(result.rows), len(records))
                self.assertEqual([m.row.raw_time for m in result.rows], expected_times)
                self.assertTrue(all(m.time_issue is None for m in result.rows))

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
