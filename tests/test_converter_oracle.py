"""Phase 2: real converter vs the frozen Phase 1 oracle (synthetic only).

This adapter reads saved PRODUCTION CSV and private textual trace. Test-only
classification and approval annotations are not production financial decisions.
"""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from acceptance.checker import ContractMismatch, EvidenceUnavailable, check_result, expected_cases
from acceptance.fixtures import ledgers, render_melli, render_mellat
from bank2odoo.core.engine import Context, convert
from bank2odoo.reporting.output import save_candidate
from bank2odoo.validation.financial import StatementError


# Test fixture context, never attributed to the converter or an accountant.
TEST_WARNINGS = [
    "FICTIONAL_TEST_ONLY",
    "JOURNAL_UNCONFIRMED",
    "FEE_ASSOCIATIONS_UNCONFIRMED",
    "CORRECTION_RELATIONSHIPS_UNCONFIRMED",
]


def evidence_line(report: str, pattern: str, what: str) -> re.Match[str]:
    match = re.search(pattern, report, re.MULTILINE)
    if not match:
        raise EvidenceUnavailable(f"Missing actual private report evidence: {what}")
    return match


def original_field(original: dict[str, str], column: int) -> str:
    values = [value for name, value in original.items() if name.endswith(f" [{column}]")]
    if len(values) != 1 or not values[0]:
        raise EvidenceUnavailable(f"Missing unique source column {column} from actual trace")
    return values[0]


def synthetic_category(source_description: str) -> str:
    """A narrow test annotation from observed synthetic text, not bank classification."""
    for marker, kind in (
        ("کارمزد آزمایشی", "fee"),
        ("اصلاحیه مستقل ساختگی", "correction"),
        ("واریز فرضی", "deposit"),
        ("انتقال ساختگی", "transfer"),
        ("انتقال آزمایشی", "transfer"),
    ):
        if source_description.startswith(marker):
            return kind
    raise EvidenceUnavailable("Synthetic-only category unsupported by actual source description")


def actual_evidence_projection(bank: str, report: str) -> dict:
    """Decode observed report statements; do not import frozen expected values."""
    if "STATUS: REVIEW CANDIDATE ONLY — NOT authorized for live Odoo import" not in report:
        raise EvidenceUnavailable("Explicit actual candidate-only status absent")
    if "No Odoo connection, journal validation, duplicate-import check, or accountant approval performed." not in report:
        raise EvidenceUnavailable("Actual non-approval notice absent")
    if "Output order: unchanged source order" not in report:
        raise EvidenceUnavailable("Output ordering disclosure absent")
    sha = evidence_line(report, r"^SHA-256 exact source bytes: ([0-9a-f]{64})$", "source hash").group(1)
    source_bank = evidence_line(report, r"^Bank: ([^;]+); Source format:", "bank").group(1)
    units = evidence_line(report, r"^Source unit: ([^;]+); target unit: ([^;]+); approved factor: (.+)$", "units")
    journal = evidence_line(report, r"^Journal \(user-entered, UNVERIFIED\): (.+)$", "journal").group(1)
    row_count = evidence_line(report, r"^Source rows: (\d+); debit rows: (\d+); credit rows: (\d+)$", "counts")
    totals = evidence_line(report, r"^Debit total \([^)]+\): ([^;]+); credit total: ([^;]+); net: (.+)$", "financial totals")
    endpoints = evidence_line(report, r"^Inferred opening/closing \(source units; not independently attested\): ([^/]+) / (.+)$", "balances")
    transitions = evidence_line(report, r"^Balance check: PASS: (\d+) consecutive balance transitions$", "balance transitions")
    observed_order = evidence_line(report, r"^Source row order: ([^;]+); Output order: unchanged source order$", "order").group(1)
    required_order = "newest-to-oldest" if bank == "melli" else "oldest-to-newest"
    if source_bank != bank or observed_order != required_order:
        raise ContractMismatch(f"Actual report bank/order contradiction: {source_bank}/{observed_order}")
    lines = [line for line in report.splitlines() if line.startswith("{")]
    if not lines:
        raise EvidenceUnavailable("No actual source-to-destination JSON trace")
    try:
        parsed = [json.loads(line) for line in lines]
    except json.JSONDecodeError as exc:
        raise ContractMismatch("Malformed actual JSON trace") from exc
    rows = []
    for expected_position, evidence in enumerate(parsed, start=1):
        orig = evidence.get("original_columns")
        if not isinstance(orig, dict):
            raise EvidenceUnavailable("Missing actual source original_columns in trace")
        # The test-only synthetic layout stores ID in Melli col 9 / Mellat col 12.
        source_id = original_field(orig, 9 if bank == "melli" else 12)
        description = original_field(orig, 8 if bank == "melli" else 5)
        if bank == "melli":
            reference = evidence["reference"]
            # independently require that actual trace reference matches physical cell 6
            if reference != original_field(orig, 6):
                raise ContractMismatch("Melli trace reference differs from physical source column")
        else:
            # Mellat production 'reference' is the bank's serial (column 4);
            # synthetic 'source_reference' lives in physical column 11.
            if evidence["reference"] != original_field(orig, 4):
                raise ContractMismatch("Mellat trace serial differs from physical source column")
            reference = original_field(orig, 11)
        source_signed = Decimal(evidence["source_signed"])
        if not source_signed.is_finite() or source_signed == 0:
            raise ContractMismatch("Invalid reported financial sign/magnitude")
        category = synthetic_category(description)
        rows.append({
            "output_row": int(evidence["csv_row"]) - 1,
            "source_row": int(evidence["source_physical_row"]),
            "source_id": source_id,
            "source_date": evidence["source_jalali_date"],
            "date": evidence["gregorian_date"],
            "source_time": evidence["source_time"],
            "source_reference": reference,
            "source_description": description,
            "label": evidence["dest_label"],
            "source_direction": "credit" if source_signed > 0 else "debit",
            "source_amount": format(abs(source_signed), "f"),
            "amount": evidence["dest_amount"],
            "balance": evidence["source_balance"],
            "category": category,  # TEST ANNOTATION from physical description only
        })
    return {
        "bank": source_bank,
        "source_sha256": sha,
        "source_unit": units.group(1),
        "destination_unit": units.group(2),
        "factor": units.group(3),
        "journal": journal,
        "opening_balance": endpoints.group(1).strip(),
        "closing_balance": endpoints.group(2).strip(),
        "debit_total": totals.group(1),
        "credit_total": totals.group(2),
        "net_movement": totals.group(3),
        "count": int(row_count.group(1)),
        "debit_count": int(row_count.group(2)),
        "credit_count": int(row_count.group(3)),
        "balance_transitions": int(transitions.group(1)),
        "fee_count": sum(row["category"] == "fee" for row in rows),
        "correction_count": sum(row["category"] == "correction" for row in rows),
        # Test-context tags required by Phase 1 checker; NEVER production claims.
        "fictional_approval": "SYNTHETIC_TEST_ONLY",
        "acceptance_status": "CANDIDATE_TEST_ONLY",
        "warnings": TEST_WARNINGS.copy(),
        "trace": rows,
    }


class RealConverterFrozenOracleAcceptance(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def prepare(self, bank: str):
        source = self.root / (bank + (".xls" if bank == "melli" else ".csv"))
        case = ledgers()[bank]
        if bank == "melli":
            render_melli(case, source)
        else:
            render_mellat(case, source)
        return source

    def production_run(self, bank):
        source = self.prepare(bank)
        # Explicit FICTIONAL IRR→IRR factor 1; synthetic journal label is not approval.
        result = convert(source, Context("IRR", "IRR", "UNCONFIRMED",
                                         approved_factor=Decimal("1")))
        output, private = self.root / "candidate.csv", self.root / "PRIVATE-report.txt"
        save_candidate(result, output, private)  # actual safe atomic publication
        return source, output, private, result

    def test_complete_melli_thirty_movements_against_frozen_oracle(self):
        self._qualify("melli", 30, 29)

    def test_complete_mellat_fifty_eight_movements_against_frozen_oracle(self):
        self._qualify("mellat", 58, 57)

    def _qualify(self, bank, count, transitions):
        source, output, private, result = self.production_run(bank)
        self.assertEqual(len(result.rows), count)
        self.assertEqual(result.balance_status,
                         f"PASS: {transitions} consecutive balance transitions")
        self.assertEqual(result.ordering, "newest-to-oldest" if bank == "melli" else "oldest-to-newest")
        text = private.read_text(encoding="utf-8")
        adapter_result = actual_evidence_projection(bank, text)
        self.assertEqual(adapter_result["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(adapter_result["journal"], "UNCONFIRMED")
        structured = self.root / "synthetic-evidence.json"
        structured.write_text(json.dumps(adapter_result, ensure_ascii=False), encoding="utf-8")
        check_result(bank, output, structured, source)
        # Additional strict byte-level equality to frozen CSV content, separate from JSON adapter.
        frozen_text = (Path(__file__).parent / "acceptance" /
                       f"expected_{bank}_csv.txt").read_text(encoding="utf-8")
        self.assertEqual(output.read_bytes(), frozen_text.encode("utf-8"))
        # The test classifications are not a production fee/reversal classifier.
        self.assertEqual(sum(x["category"] == "fee" for x in adapter_result["trace"]),
                         expected_cases()[bank]["fee_count"])
        self.assertEqual(sum(x["category"] == "correction" for x in adapter_result["trace"]),
                         expected_cases()[bank]["correction_count"])

    def test_broken_source_balance_fails_closed_before_writing_files(self):
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                mutated = ledgers()[bank]
                mutated["rows"][5]["balance"] = "1"
                source = self.root / (f"corrupt_{bank}" + (".xls" if bank == "melli" else ".csv"))
                if bank == "melli":
                    render_melli(mutated, source)
                else:
                    render_mellat(mutated, source)
                with self.assertRaisesRegex(StatementError, "balance mismatch"):
                    convert(source, Context("IRR", "IRR", "UNCONFIRMED", approved_factor=Decimal("1")))
                self.assertFalse((self.root/"candidate.csv").exists())
                self.assertFalse((self.root/"PRIVATE-report.txt").exists())

    def test_tampered_actual_trace_identity_is_rejected_for_both_banks(self):
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                source, output, private, _ = self.production_run(bank)
                lines = private.read_text(encoding="utf-8").splitlines()
                first_trace = next(i for i, line in enumerate(lines) if line.startswith("{"))
                entry = json.loads(lines[first_trace])
                physical_column = 9 if bank == "melli" else 12
                key = next(k for k in entry["original_columns"] if k.endswith(f" [{physical_column}]"))
                entry["original_columns"][key] = "FAKE-SOURCE-ID"
                lines[first_trace] = json.dumps(entry, ensure_ascii=False, sort_keys=True)
                private.write_text("\n".join(lines) + "\n", encoding="utf-8")
                evidence = actual_evidence_projection(bank, private.read_text(encoding="utf-8"))
                projected = self.root / "synthetic-evidence.json"
                projected.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
                with self.assertRaisesRegex(ContractMismatch, "trace source_id at 1"):
                    check_result(bank, output, projected, source)

    def test_missing_original_source_identity_is_not_manufactured(self):
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                _, _, private, _ = self.production_run(bank)
                lines = private.read_text(encoding="utf-8").splitlines()
                first_trace = next(i for i, line in enumerate(lines) if line.startswith("{"))
                entry = json.loads(lines[first_trace])
                physical_column = 9 if bank == "melli" else 12
                key = next(k for k in entry["original_columns"] if k.endswith(f" [{physical_column}]"))
                del entry["original_columns"][key]
                lines[first_trace] = json.dumps(entry, ensure_ascii=False, sort_keys=True)
                with self.assertRaisesRegex(EvidenceUnavailable, "source column"):
                    actual_evidence_projection(bank, "\n".join(lines) + "\n")

    def test_missing_real_report_evidence_does_not_gain_synthetic_status(self):
        for bank in ("melli", "mellat"):
            with self.subTest(bank=bank):
                with self.assertRaises(EvidenceUnavailable):
                    actual_evidence_projection(bank, "STATUS: REVIEW CANDIDATE ONLY")

