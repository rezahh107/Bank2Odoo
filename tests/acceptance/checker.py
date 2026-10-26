"""Production-independent, reference-frozen acceptance checker (Phase 1)."""
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .fixtures import ledgers, render_melli, render_mellat

BASE = Path(__file__).parent
EXPECTED_FIELDS = ('output_row', 'source_row', 'source_id', 'source_date', 'date',
    'source_time', 'source_reference', 'source_description', 'label',
    'source_direction', 'source_amount', 'amount', 'balance', 'category')
SUMMARY_FIELDS = ('opening_balance', 'closing_balance', 'debit_total', 'credit_total',
    'net_movement', 'count', 'debit_count', 'credit_count', 'fee_count',
    'correction_count', 'balance_transitions')


class ContractMismatch(AssertionError):
    pass


class EvidenceUnavailable(FileNotFoundError):
    pass


def expected_cases():
    return json.loads((BASE/'frozen_expected.json').read_text(encoding='utf-8'))['cases']


def require_equal(value, expected, context):
    if value != expected:
        raise ContractMismatch(f'{context}: expected {expected!r}, got {value!r}')


def _decimal(value, context):
    try:
        value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ContractMismatch(f'{context}: invalid decimal') from exc
    if not value.is_finite():
        raise ContractMismatch(f'{context}: non-finite decimal')
    return value


def validate_reference(bank, *, source=None, reference=None):
    """Cross-check two separately versioned static ledgers; never invoke a converter."""
    source = source if source is not None else ledgers()[bank]
    reference = reference if reference is not None else expected_cases()[bank]
    entries, rows = source['rows'], reference['rows']
    expected_text = (BASE/f'expected_{bank}_csv.txt').read_text(encoding='utf-8')
    expected_csv = list(csv.reader(expected_text.splitlines()))
    require_equal(expected_csv[0], ['Date', 'Label', 'Amount'], 'frozen CSV header')
    require_equal(expected_csv[1:], [[r['date'], r['label'], r['amount']] for r in rows], 'frozen CSV content')
    require_equal(len(entries), reference['count'], 'source count')
    require_equal(len(rows), len(entries), 'expected count')
    require_equal(source['bank'], reference['bank'], 'bank name')
    require_equal(source['opening_balance'], reference['opening_balance'], 'opening balance')
    require_equal(source['closing_balance'], reference['closing_balance'], 'closing balance')
    for key in ('source_unit', 'destination_unit', 'factor', 'fictional_approval'):
        require_equal(source[key], reference[key], key)
    require_equal(source['factor'], '1', 'approved test unit factor')
    require_equal(source['fictional_approval'], 'SYNTHETIC_TEST_ONLY', 'approval marker')
    count = {'debit': 0, 'credit': 0, 'fee': 0, 'correction': 0}
    totals = {'debit': Decimal(0), 'credit': Decimal(0)}
    chronological = list(reversed(entries)) if bank == 'melli' else entries
    running = _decimal(source['opening_balance'], 'opening balance')
    for index, item in enumerate(chronological):
        signed = _decimal(item['amount'], 'source amount')
        if signed <= 0 or item['direction'] not in ('debit', 'credit'):
            raise ContractMismatch(f'source transaction {item["id"]}: invalid direction or amount')
        totals[item['direction']] += signed
        count[item['direction']] += 1
        if item['category'] in ('fee', 'correction'):
            count[item['category']] += 1
        if item['category'] == 'fee' and item['direction'] != 'debit':
            raise ContractMismatch('fee direction')
        if item['category'] == 'correction' and item['direction'] != 'credit':
            raise ContractMismatch('correction direction')
        running += signed if item['direction'] == 'credit' else -signed
        require_equal(_decimal(item['balance'], 'source balance'), running,
                      f'source balance at {item["id"]}')
    require_equal(running, _decimal(reference['closing_balance'], 'closing balance'), 'closing balance')
    for kind in ('debit', 'credit'):
        require_equal(count[kind], reference[f'{kind}_count'], f'{kind} count')
        require_equal(totals[kind], _decimal(reference[f'{kind}_total'], f'{kind} total'), f'{kind} total')
    for category in ('fee', 'correction'):
        require_equal(count[category], reference[f'{category}_count'], f'{category} count')
    require_equal(totals['credit'] - totals['debit'],
                  _decimal(reference['net_movement'], 'net movement'), 'net movement')
    require_equal(reference['balance_transitions'], len(entries)-1, 'balance transition count')
    require_equal(_decimal(reference['opening_balance'], 'opening balance') +
                  _decimal(reference['net_movement'], 'net movement'), running, 'period balance equation')
    require_equal(len(set(r['id'] for r in entries)), len(entries), 'source identifiers uniqueness')
    require_equal(len(set(r['source_row'] for r in entries)), len(entries), 'source physical rows uniqueness')
    for idx, (item, dest) in enumerate(zip(entries, rows), 1):
        require_equal(item['source_row'], source['header_row'] + idx, f'physical source row {idx}')
        require_equal(item['id'], dest['source_id'], f'source id at {idx}')
        require_equal(idx, dest['output_row'], f'output index at {idx}')
        for src, dst in (('source_row','source_row'), ('date','source_date'),
                         ('time','source_time'), ('reference','source_reference'),
                         ('description','source_description'), ('description','label'),
                         ('direction','source_direction'), ('amount','source_amount'),
                         ('balance','balance'), ('category','category'), ('gregorian','date')):
            require_equal(item[src], dest[dst], f'{dst} at {idx}')
        sign = 1 if item['direction'] == 'credit' else -1
        require_equal(_decimal(dest['amount'], 'signed amount'), sign * _decimal(item['amount'], 'source amount'),
                      f'expected signed amount at {idx}')
        # For this bounded synthetic ledger, every date lies in Mehr 1405.
        day = int(item['date'].split('/')[-1])
        require_equal(item['date'][:8], '1405/07/', f'Jalali date at {idx}')
        require_equal(item['gregorian'], (date(2026, 9, 23) + timedelta(days=day-1)).isoformat(),
                      f'Gregorian date at {idx}')
        if idx > 1:
            prev = entries[idx-2]
            actual_delta = _decimal(item['balance'], 'balance') - _decimal(prev['balance'], 'balance')
            # Descending: prior/newer balance minus current/older balance = signed(prior).
            transaction = prev if bank == 'melli' else item
            wanted = _decimal(transaction['amount'], 'amount') * (1 if transaction['direction']=='credit' else -1)
            if bank == 'melli':
                actual_delta = -actual_delta
            require_equal(actual_delta, wanted, f'consecutive balance at {idx}')
    return len(entries)-1


def _require_canonical_source(bank, source_path):
    """Bind actual source bytes to the ledger-backed, frozen synthetic fixture."""
    # The ledger must still agree with the separate, frozen expected references.
    try:
        validate_reference(bank)
        with TemporaryDirectory() as temporary:
            canonical = Path(temporary) / ('synthetic.xls' if bank == 'melli' else 'synthetic.csv')
            if bank == 'melli':
                render_melli(ledgers()[bank], canonical)
            elif bank == 'mellat':
                render_mellat(ledgers()[bank], canonical)
            else:
                raise ContractMismatch(f'Unsupported synthetic bank: {bank}')
            if Path(source_path).read_bytes() != canonical.read_bytes():
                raise ContractMismatch(f'{bank}: source bytes differ from canonical synthetic source')
    except FileNotFoundError as exc:
        raise EvidenceUnavailable(f'canonical source evidence unavailable: {exc}') from exc


def check_result(bank, csv_path, report_path, source_path):
    """Compare future *actual* outputs with immutable expected material.

    Missing input/report evidence is not a mathematics failure and cannot pass.
    """
    ref = expected_cases()[bank]
    for path in (csv_path, report_path, source_path):
        if not Path(path).is_file():
            raise EvidenceUnavailable(f'evidence file unavailable: {path}')
    try:
        with Path(csv_path).open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, strict=True)
            header = next(reader, None)
            require_equal(header, ['Date', 'Label', 'Amount'], 'CSV header')
            actual = list(reader)
        with Path(report_path).open('r', encoding='utf-8') as f:
            report = json.load(f)
    except (UnicodeError, ValueError, csv.Error, OSError) as exc:
        raise ContractMismatch('Malformed CSV/report evidence') from exc
    require_equal(len(actual), ref['count'], 'CSV row count')
    for idx, (actual_row, expected_row) in enumerate(zip(actual, ref['rows']), 1):
        require_equal(len(actual_row), 3, f'CSV column count at {idx}')
        for col, key in enumerate(('date', 'label', 'amount')):
            require_equal(actual_row[col], expected_row[key], f'CSV {key} at {idx}')
    for key in ('bank', 'source_unit', 'destination_unit', 'factor', 'fictional_approval',
                'acceptance_status', 'warnings', *SUMMARY_FIELDS):
        require_equal(report.get(key), ref[key], f'report {key}')
    require_equal(report.get('journal'), 'UNCONFIRMED', 'report journal')
    require_equal(report.get('source_sha256'), hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
                  'source file hash')
    require_equal(len(report.get('trace', [])), len(ref['rows']), 'trace count')
    for idx, (actual_trace, expected_row) in enumerate(zip(report['trace'], ref['rows']), 1):
        for key in EXPECTED_FIELDS:
            require_equal(actual_trace.get(key), expected_row[key], f'trace {key} at {idx}')
    _require_canonical_source(bank, source_path)
    return {'bank':bank, 'count':ref['count'], 'status':'SYNTHETIC_REFERENCE_MATCH_ONLY'}
