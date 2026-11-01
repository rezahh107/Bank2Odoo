"""Fail-closed balance-gap regression tests; all statement data is synthetic."""

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest

from bank2odoo.core.engine import BalanceGapApproval, Context, convert
from bank2odoo.reporting.output import output_csv, save_candidate
from bank2odoo.validation.financial import StatementError
from test_conversion import write_melli


def fictional_movements():
    # Newest first; physical XLS rows 7, 8 | 9, 10.
    # First segment: 180 - 170 = +10. Second: 95 - 100 = -5.
    # Missing interval: 170 - 95 - 20 = +55 (fictional source units).
    return [
        ["4", "1405/07/04", "12:00:00", "واریز", "10", "SYN-4", "",
         "واریز روز چهارم", "", "180"],
        ["3", "1405/07/03", "12:00:00", "واریز", "20", "SYN-3", "",
         "واریز روز سوم", "", "170"],
        ["2", "1405/07/02", "12:00:00", "برداشت", "5", "SYN-2", "",
         "برداشت روز دوم", "", "95"],
        ["1", "1405/07/01", "12:00:00", "واریز", "5", "SYN-1", "",
         "واریز روز اول", "", "100"],
    ]


class ApprovedBalanceGapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / "fictional.xls"
        self.rows = fictional_movements()
        self._write()

    def _write(self):
        write_melli(self.source, self.rows)

    def _approval(self):
        return BalanceGapApproval(
            source_sha256=sha256(self.source.read_bytes()).hexdigest(),
            preceding_physical_row=8,
            following_physical_row=9,
            expected_residual=Decimal("55"),
        )

    def _convert(self, approval=None):
        return convert(self.source, Context(
            "IRR", "IRR", "Synthetic Journal",
            balance_gap_approval=approval,
        ))

    def test_without_gap_approval_original_hard_failure_is_preserved(self):
        with self.assertRaisesRegex(StatementError, "balance mismatch.*8/9"):
            self._convert()

    def test_sha_bound_gap_validates_both_segments_without_full_period_pass(self):
        result = self._convert(self._approval())
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(result.ordering, "newest-to-oldest")
        self.assertTrue(result.balance_status.startswith("NOT_PROVEN:"))
        self.assertIn("1+1 strict within-segment transitions", result.balance_status)
        self.assertIsNone(result.opening)
        self.assertIsNone(result.closing)
        self.assertEqual(result.net, Decimal("30"))
        self.assertIn("whole-period opening/closing and continuity NOT_PROVEN",
                      "\n".join(result.issues))
        expected = (
            "Date,Label,Amount\n"
            "2026-09-26,واریز روز چهارم,10\n"
            "2026-09-25,واریز روز سوم,20\n"
            "2026-09-24,برداشت روز دوم,-5\n"
            "2026-09-23,واریز روز اول,5\n"
        )
        self.assertEqual(output_csv(result), expected)
        csv_path = self.folder / "candidate.csv"
        report_path = self.folder / "PRIVATE_control.txt"
        save_candidate(result, csv_path, report_path)
        self.assertEqual(csv_path.read_bytes(), expected.encode("utf-8"))
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("Balance check: NOT_PROVEN:", report)
        self.assertIn("not independently attested by software", report)
        trace = [json.loads(line) for line in report.splitlines() if line.startswith("{")]
        self.assertEqual([r["source_physical_row"] for r in trace], [7, 8, 9, 10])
        self.assertEqual([r["csv_row"] for r in trace], [2, 3, 4, 5])
        self.assertEqual([r["dest_amount"] for r in trace], ["10", "20", "-5", "5"])

    def test_wrong_sha_boundary_and_residual_are_rejected(self):
        original = self._approval()
        mismatched = [
            replace(original, source_sha256="0" * 64),
            replace(original, preceding_physical_row=7, following_physical_row=8),
            replace(original, expected_residual=Decimal("54")),
            replace(original, expected_residual=Decimal("0")),
            replace(original, expected_residual=Decimal("NaN")),
        ]
        for approval in mismatched:
            with self.subTest(approval=approval), self.assertRaises(StatementError):
                self._convert(approval)

        # An approval for a past file cannot authorize its mutated successor.
        self.rows[0][7] = "ویرایش آزمایشی"
        self._write()
        with self.assertRaisesRegex(StatementError, "SHA-256"):
            self._convert(original)

    def test_corruption_unknown_extra_gap_missing_row_and_source_reorder(self):
        # Even after a freshly scoped, explicit gap approval, other defects remain fatal.
        baseline = fictional_movements()
        variants = []
        changed = [list(row) for row in baseline]
        changed[0][9] = "181"  # Unexpected discrepancy in the newer segment.
        variants.append(changed)
        changed = [list(row) for row in baseline]
        changed[3][9] = "101"  # Unexpected discrepancy in the older segment.
        variants.append(changed)
        changed = [list(row) for row in baseline]
        changed[0][4] = "11"  # Corrupt the signed amount, not the balance.
        variants.append(changed)
        variants.append([list(row) for i, row in enumerate(baseline) if i != 0])
        variants.append([list(row) for row in reversed(baseline)])
        for index, variant in enumerate(variants):
            with self.subTest(case=index):
                self.rows = variant
                self._write()
                # Test a fresh per-source SHA as well, not just stale-hash rejection.
                with self.assertRaises(StatementError):
                    self._convert(self._approval())

    def test_unused_approval_does_not_convert_continuous_chain_into_gap(self):
        # Remove fictional missing interval while keeping both segments internally sound.
        self.rows[2][9] = "150"
        self.rows[3][9] = "155"
        self._write()
        self.assertEqual(self._convert().balance_status,
                         "PASS: 3 consecutive balance transitions")
        with self.assertRaisesRegex(StatementError, "not found"):
            self._convert(self._approval())


if __name__ == "__main__":
    unittest.main()
