"""Journal-free production conversion regression; fictional sources only."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting.output import output_csv, control_report
from bank2odoo.validation.financial import StatementError
from tests.test_conversion import write_mellat

ROOT = Path(__file__).resolve().parents[1]


class OptionalJournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="b2o-fictional-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "fictional.csv"
        write_mellat(self.source, [
            ["1", "1405/07/01", "10:00:00", "001", "واریز آزمایشی", "0", "100", "100"],
            ["2", "1405/07/02", "11:00:00", "002", "کارمزد آزمایشی", "25", "0", "75"],
        ])

    def _cli(self, name, *extra):
        csv_path = self.root / (name + ".csv")
        report_path = self.root / (name + ".txt")
        command = [sys.executable, "-m", "bank2odoo",
                   "--input", str(self.source), "--output", str(csv_path),
                   "--report", str(report_path), "--source-unit", "IRR",
                   "--target-unit", "IRR", "--decimal-places", "0", *extra]
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        return proc, csv_path, report_path

    def test_cli_without_journal_and_legacy_cli_have_identical_csv(self):
        fresh, csv1, report1 = self._cli("without")
        old, csv2, report2 = self._cli("legacy", "--journal", "Legacy Fictional Journal")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertEqual(csv1.read_bytes(), csv2.read_bytes())
        with csv1.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["Date", "Label", "Amount"])
        self.assertEqual(len(rows), 3)
        self.assertEqual([r[2] for r in rows[1:]], ["100", "-25"])
        self.assertIn("select the correct Bank Journal separately inside Odoo",
                      report1.read_text(encoding="utf-8"))
        self.assertIn("Journal (user-entered, UNVERIFIED): Legacy Fictional Journal",
                      report2.read_text(encoding="utf-8"))
        for path in (report1, report2):
            report = path.read_text(encoding="utf-8")
            lines = report.split("## Source-to-destination trace (JSON objects, one per output row; private)\n", 1)[1].splitlines()
            trace = [json.loads(line) for line in lines]
            self.assertEqual([item["csv_row"] for item in trace], [2, 3])
            self.assertTrue(all(item["original_columns"] for item in trace))
            self.assertTrue(all(item["source_physical_row"] for item in trace))
            self.assertIn("Balance check:", report)
            self.assertIn("REVIEW CANDIDATE ONLY", report)

    def test_python_context_legacy_positional_and_keyword_compatibility(self):
        new = convert(self.source, Context("IRR", "IRR"))
        legacy = convert(self.source, Context("IRR", "IRR", "Legacy Fictional Journal", 0))
        keyword = convert(self.source, Context("IRR", "IRR", journal="Label only"))
        self.assertEqual(output_csv(new), output_csv(legacy))
        self.assertEqual(output_csv(new), output_csv(keyword))
        self.assertEqual(len(new.rows), 2)
        self.assertEqual(new.journal, "")
        self.assertIn("separately inside Odoo", control_report(new))

    def test_journal_is_not_a_validation_bypass(self):
        for context in (
            Context("UNKNOWN", "IRR"),
            Context("IRR", "UNKNOWN"),
            Context("TOMAN", "IRR"),
            Context("TOMAN", "IRR", approved_factor=Decimal("11")),
            Context("TOMAN", "IRR", approved_factor=Decimal("NaN")),
            Context("IRR", "IRR", decimal_places=-1),
            Context("IRR", "IRR", decimal_places=10),
        ):
            with self.subTest(context=context), self.assertRaises(StatementError):
                convert(self.source, context)
        bad = self.root / "bad_date.csv"
        write_mellat(bad, [["1", "1405/13/01", "10:00", "1", "تاریخ نادرست", "0", "5", "5"]])
        with self.assertRaisesRegex(StatementError, "date"):
            convert(bad, Context("IRR", "IRR"))
        self.assertEqual(list(self.root.glob("*.txt")), [])


if __name__ == "__main__":
    unittest.main()
