"""Phase 1: qualify independent synthetic inputs/oracle/checker, NOT the converter."""
import copy
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acceptance.checker import (ContractMismatch, EvidenceUnavailable, check_result,
                                 expected_cases, validate_reference)
from acceptance.fixtures import (MELLI_HEADERS, MELLAT_HEADERS, ledgers,
    render_melli, render_mellat, render_small_cp1256, render_small_utf8_bom)
from acceptance.probe import inspect_biff8


class ReferenceQualification(unittest.TestCase):
    def test_independent_ledger_arithmetic_chronology_and_fixed_dates(self):
        required = {'melli': (30, 21, 9, 10, 2, 29),
                    'mellat': (58, 43, 15, 13, 2, 57)}
        for bank, numbers in required.items():
            with self.subTest(bank=bank):
                ref = expected_cases()[bank]
                got = (ref['count'], ref['debit_count'], ref['credit_count'],
                       ref['fee_count'], ref['correction_count'], ref['balance_transitions'])
                self.assertEqual(got, numbers)
                self.assertEqual(validate_reference(bank), numbers[-1])
                times = [(r['source_date'], r['source_time']) for r in ref['rows']]
                self.assertEqual(times, sorted(times, reverse=(bank == 'melli')))
                self.assertEqual(len(set(r['source_id'] for r in ref['rows'])), numbers[0])
                self.assertEqual(len(set(r['source_row'] for r in ref['rows'])), numbers[0])
                self.assertEqual(Decimal(ref['opening_balance']) + Decimal(ref['net_movement']),
                                 Decimal(ref['closing_balance']))

    def assert_melli_readback(self, path, case):
        self.assertEqual(path.read_bytes()[:8], bytes.fromhex('D0CF11E0A1B11AE1'))
        cells = inspect_biff8(path)  # Independently decoded physical BIFF8 cells.
        self.assertEqual([cells[4, i] for i in range(14)], list(MELLI_HEADERS))
        self.assertEqual(len([key for key in cells if key[1] == 3 and 5 <= key[0] <= 34]), 30)
        for idx, entry in enumerate(case['rows']):
            row = idx + 5  # Zero-based physical row.
            self.assertEqual(cells[row, 1], entry['date'])
            self.assertEqual(cells[row, 2], entry['time'])
            self.assertEqual(cells[row, 3], 'برداشت' if entry['direction'] == 'debit' else 'واریز')
            self.assertEqual(cells[row, 4], int(entry['amount']))
            self.assertEqual(cells[row, 5], entry['reference'])
            self.assertEqual(cells[row, 7], entry['description'])
            self.assertEqual(cells[row, 9], int(entry['balance']))

    def test_binary_melli_is_parseable_ole_biff8_not_disguised_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            path = render_melli(ledgers()['melli'], Path(temp)/'synthetic.xls')
            self.assert_melli_readback(path, ledgers()['melli'])

    def assert_mellat_readback(self, path, case):
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        with path.open(encoding='utf-8-sig', newline='') as handle:
            lines = list(csv.reader(handle))
        self.assertEqual(len(lines), 61)  # 2 non-data rows + header + 58 movements
        self.assertEqual(tuple(lines[2]), MELLAT_HEADERS)
        for idx, (source, actual) in enumerate(zip(case['rows'], lines[3:]), 1):
            self.assertEqual(len(actual), 12)
            self.assertEqual(actual[1], source['date'])
            self.assertEqual(actual[3], source['serial'])
            self.assertTrue(actual[3].startswith('000'))
            self.assertEqual(actual[4], source['description'])
            self.assertEqual(actual[5], source['amount'] if source['direction']=='debit' else '0')
            self.assertEqual(actual[6], source['amount'] if source['direction']=='credit' else '0')
            self.assertEqual(actual[7], source['balance'])


    def test_mellat_utf8_bom_readback_and_cp1256_edge_case(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            path = render_mellat(ledgers()['mellat'], temp/'synthetic.csv')
            self.assert_mellat_readback(path, ledgers()['mellat'])
            bom = render_small_utf8_bom(temp/'utf8.csv')
            cp = render_small_cp1256(temp/'cp.csv')
            with bom.open(encoding='utf-8-sig', newline='') as handle:
                self.assertEqual(next(csv.reader(handle)), list(MELLAT_HEADERS))
            with cp.open(encoding='cp1256', newline='') as handle:
                cp_rows = list(csv.reader(handle))
            self.assertEqual(len(cp_rows[0]), 12)
            self.assertEqual(cp_rows[1][3], '0000025')
            self.assertIn('كارمزد', cp_rows[1][4])

    def test_melli_generator_identity_corruption_is_detected(self):
        original = ledgers()['melli']
        for field, context in (('id', 'Melli source ID row 1'), ('serial', 'Melli serial row 1')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                corrupted = copy.deepcopy(original)
                corrupted['rows'][0][field] += '-ALTERED'
                path = render_melli(corrupted, Path(temp)/'corrupted.xls')
                # Oracle remains the unchanged source ledger, not the generator's input.
                with self.assertRaisesRegex(AssertionError, context):
                    self.assert_melli_readback(path, original)

    def test_mellat_generator_identity_corruption_is_detected(self):
        original = ledgers()['mellat']
        for field, context in (('reference', 'Mellat reference row 1'), ('id', 'Mellat source ID row 1')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                corrupted = copy.deepcopy(original)
                corrupted['rows'][0][field] += '-ALTERED'
                path = render_mellat(corrupted, Path(temp)/'corrupted.csv')
                # Only generator-side input changes; frozen oracle and output remain intact.
                with self.assertRaisesRegex(AssertionError, context):
                    self.assert_mellat_readback(path, original)


    def test_ledger_source_mutations_rejected(self):
        for bank in ('melli', 'mellat'):
            source = ledgers()[bank]
            for name, edit, reason in (
                ('changed balance', lambda s: s['rows'][0].update(balance='3'), 'source balance'),
                ('changed amount', lambda s: s['rows'][0].update(amount='3'), 'source balance'),
                ('missing source movement', lambda s: s['rows'].pop(), 'source count'),
                ('invalid direction', lambda s: s['rows'][0].update(direction='unknown'), 'invalid direction'),
            ):
                with self.subTest(bank=bank, mutation=name):
                    candidate = copy.deepcopy(source)
                    edit(candidate)
                    with self.assertRaisesRegex(ContractMismatch, reason):
                        validate_reference(bank, source=candidate)


class CheckerMutationQualification(unittest.TestCase):
    """Candidate constructed from frozen reference is a self-test, not converter output."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = ledgers()
        self.ref = expected_cases()

    def sample(self, bank):
        csv_path = self.root/f'{bank}_test_candidate.csv'
        trace_path = self.root/f'{bank}_test_report.json'
        source_path = self.root/(f'{bank}.xls' if bank=='melli' else f'{bank}.csv')
        if bank=='melli': render_melli(self.cases[bank], source_path)
        else: render_mellat(self.cases[bank], source_path)
        with csv_path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle, lineterminator='\n')
            writer.writerow(['Date', 'Label', 'Amount'])
            writer.writerows((r['date'], r['label'], r['amount']) for r in self.ref[bank]['rows'])
        report = {key: copy.deepcopy(value) for key,value in self.ref[bank].items() if key != 'rows'}
        report.update(trace=copy.deepcopy(self.ref[bank]['rows']), journal='UNCONFIRMED',
                      source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())
        trace_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        return csv_path, trace_path, source_path

    def load_candidate(self, paths):
        with paths[0].open(encoding='utf-8', newline='') as handle:
            table = list(csv.reader(handle))
        return table, json.loads(paths[1].read_text(encoding='utf-8'))

    def write_candidate(self, paths, table, report):
        with paths[0].open('w', encoding='utf-8', newline='') as handle:
            csv.writer(handle, lineterminator='\n').writerows(table)
        paths[1].write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')

    def test_unmodified_frozen_reference_passes_for_both_banks(self):
        for bank in ('melli','mellat'):
            with self.subTest(bank=bank):
                paths = self.sample(bank)
                self.assertEqual(check_result(bank, *paths)['count'], self.ref[bank]['count'])

    def test_meaningful_output_and_report_mutations_are_detected(self):
        changes = (
            ('amount', lambda t,r: t[1].__setitem__(2, '999'), 'CSV amount at 1'),
            ('sign', lambda t,r: t[1].__setitem__(2, str(-int(t[1][2]))), 'CSV amount at 1'),
            ('precision', lambda t,r: t[1].__setitem__(2, t[1][2]+'.01'), 'CSV amount at 1'),
            ('missing', lambda t,r: t.pop(1), 'CSV row count'),
            ('extra', lambda t,r: t.append(copy.deepcopy(t[-1])), 'CSV row count'),
            ('reordered', lambda t,r: t.__setitem__(slice(1,3), t[1:3][::-1]), 'CSV date at 1|CSV label at 1'),
            ('Gregorian', lambda t,r: t[1].__setitem__(0, '2026-09-22'), 'CSV date at 1'),
            ('description', lambda t,r: t[1].__setitem__(1, 'شرح دستکاری شد'), 'CSV label at 1'),
            ('missing description', lambda t,r: t[1].__setitem__(1, ''), 'CSV label at 1'),
            ('CSV columns', lambda t,r: t[0].append('Source'), 'CSV header'),
            ('source mapping', lambda t,r: r['trace'][0].update(source_row=888), 'trace source_row at 1'),
            ('trace id', lambda t,r: r['trace'][0].update(source_id='WRONG'), 'trace source_id at 1'),
            ('opening', lambda t,r: r.update(opening_balance='0'), 'report opening_balance'),
            ('closing', lambda t,r: r.update(closing_balance='0'), 'report closing_balance'),
            ('chain', lambda t,r: r['trace'][1].update(balance='0'), 'trace balance at 2'),
            ('fee', lambda t,r: next(x for x in r['trace'] if x['category']=='fee').update(category='transfer'), 'trace category'),
            ('correction', lambda t,r: next(x for x in r['trace'] if x['category']=='correction').update(category='deposit'), 'trace category'),
            ('unit', lambda t,r: r.update(destination_unit='IRT'), 'report destination_unit'),
            ('factor', lambda t,r: r.update(factor='10'), 'report factor'),
            ('totals', lambda t,r: r.update(net_movement='0'), 'report net_movement'),
            ('missing status', lambda t,r: r.pop('acceptance_status'), 'report acceptance_status'),
            ('misleading status', lambda t,r: r.update(acceptance_status='READY_FOR_PRODUCTION'), 'report acceptance_status'),
            ('missing warning', lambda t,r: r.update(warnings=[]), 'report warnings'),
            ('source hash', lambda t,r: r.update(source_sha256='fake'), 'source file hash'),
        )
        for bank in ('melli','mellat'):
            for label, action, failure in changes:
                with self.subTest(bank=bank, mutation=label):
                    paths = self.sample(bank)
                    table, report = self.load_candidate(paths)
                    action(table, report)
                    self.write_candidate(paths, table, report)
                    with self.assertRaisesRegex(ContractMismatch, failure):
                        check_result(bank, *paths)

    def assert_source_rejected_with_matching_report_hash(self, bank, paths):
        # All candidate CSV/trace fields remain frozen; only the supplied bank
        # source changes. A self-consistent report hash must not authorize it.
        table, report = self.load_candidate(paths)
        report['source_sha256'] = hashlib.sha256(paths[2].read_bytes()).hexdigest()
        self.write_candidate(paths, table, report)
        with self.assertRaisesRegex(ContractMismatch, 'canonical synthetic source'):
            check_result(bank, *paths)

    def test_substituted_source_with_matching_report_hash_is_rejected_for_both_banks(self):
        for bank in ('melli', 'mellat'):
            with self.subTest(bank=bank):
                paths = self.sample(bank)
                altered = copy.deepcopy(self.cases[bank])
                altered['rows'][0]['reference'] += '-CHANGED'
                if bank == 'melli':
                    render_melli(altered, paths[2])
                    self.assertEqual(len(inspect_biff8(paths[2])),
                                     len(inspect_biff8(render_melli(self.cases[bank], self.root/'original.xls'))))
                else:
                    render_mellat(altered, paths[2])
                self.assert_source_rejected_with_matching_report_hash(bank, paths)

    def test_melli_modified_xls_bytes_with_matching_report_hash_are_rejected(self):
        paths = self.sample('melli')
        source = paths[2]
        original = source.read_bytes()
        reference = self.cases['melli']['rows'][0]['reference']
        before = reference.encode('utf-16le')
        after = reference.replace('TEST', 'TAST', 1).encode('utf-16le')
        self.assertEqual(original.count(before), 1)
        source.write_bytes(original.replace(before, after, 1))
        self.assertIn(reference.replace('TEST', 'TAST', 1), inspect_biff8(source).values())
        self.assert_source_rejected_with_matching_report_hash('melli', paths)

    def test_mellat_modified_csv_bytes_and_leading_zero_serial_are_rejected(self):
        bank = 'mellat'
        serial = self.cases[bank]['rows'][0]['serial']
        description = self.cases[bank]['rows'][-1]['description']
        for mutation, before, after in (
            ('lost leading zero', serial.encode('utf-8'), serial[1:].encode('utf-8')),
            ('changed description', description.encode('utf-8'),
             (description + ' اضافه').encode('utf-8')),
        ):
            with self.subTest(mutation=mutation):
                paths = self.sample(bank)
                original = paths[2].read_bytes()
                self.assertEqual(original.count(before), 1)
                paths[2].write_bytes(original.replace(before, after, 1))
                with paths[2].open(encoding='utf-8-sig', newline='') as handle:
                    rows = list(csv.reader(handle))
                self.assertEqual(len(rows), 61)
                self.assertEqual(len(rows[3]), 12)
                if mutation == 'lost leading zero':
                    self.assertEqual(rows[3][3], serial[1:])
                else:
                    self.assertEqual(rows[-1][4], description + ' اضافه')
                self.assert_source_rejected_with_matching_report_hash(bank, paths)

    def test_missing_source_file_is_evidence_unavailable_for_both_banks(self):
        for bank in ('melli', 'mellat'):
            with self.subTest(bank=bank):
                paths = self.sample(bank)
                paths[2].unlink()
                with self.assertRaises(EvidenceUnavailable):
                    check_result(bank, *paths)

    def test_missing_evidence_is_not_a_pass_or_math_failure(self):
        paths = self.sample('melli')
        paths[1].unlink()
        with self.assertRaisesRegex(EvidenceUnavailable, 'unavailable'):
            check_result('melli', *paths)


if __name__ == '__main__':
    unittest.main()
