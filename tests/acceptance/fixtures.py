"""Test-only, deterministic legacy BIFF8/OLE and CSV generators; no converter imports."""
import csv
import json
from pathlib import Path
import struct

BASE = Path(__file__).resolve().parent
MELLI_HEADERS = ('ردیف', 'تاریخ', 'زمان', 'نوع', 'مبلغ', 'شماره پیگیری',
                 'اطلاعات تکمیلی', 'شرح', 'توضیحات', 'مانده', 'کانال', 'شعبه',
                 'شناسه سند', 'ستون کمکی')
MELLAT_HEADERS = ('رديف', 'تاریخ', 'زمان', 'شماره سریال', 'شرح',
                  'مبلغ گردش بدهکار', 'مبلغ گردش بستانکار', 'مانده',
                  'ذینفع', 'کانال', 'شناسه دستور', 'توضیحات')


def ledgers():
    return {case['bank']: case for case in json.loads(
        (BASE / 'source_ledger.json').read_text(encoding='utf-8'))['cases']}


def _record(code, payload=b''):
    return struct.pack('<HH', code, len(payload)) + payload


def _bof(document_type):
    return _record(0x0809, struct.pack('<HHHHII', 0x0600, document_type, 0x0DBB, 1996, 0, 6))


def _label(row, col, value):
    """BIFF8 LABEL: Unicode without SST, supported by legacy .xls readers."""
    value = str(value)
    payload = struct.pack('<HHHHB', row, col, 0, len(value), 1) + value.encode('utf-16le')
    return _record(0x0204, payload)


def _number(row, col, value):
    return _record(0x0203, struct.pack('<HHHd', row, col, 0, float(value)))


def _worksheet(matrix):
    records = [_bof(0x0010), _record(0x0200, struct.pack('<IIHHH', 0, len(matrix), 0, 14, 0))]
    for row_num, cells in enumerate(matrix):
        for col_num, value in enumerate(cells):
            if value is None or value == '':
                continue
            if isinstance(value, int):
                records.append(_number(row_num, col_num, value))
            else:
                records.append(_label(row_num, col_num, value))
    records.append(_record(0x000A))
    return b''.join(records)


def _workbook(matrix):
    sheet = _worksheet(matrix)
    name = b'Synthetic'
    boundsheet = _record(0x0085, struct.pack('<IBBB', 0, 0, 0, len(name)) + b'\0' + name)
    globals_prefix = _bof(0x0005) + _record(0x0042, struct.pack('<H', 1200)) + _record(0x0022, b'\0\0')
    sheet_offset = len(globals_prefix) + len(boundsheet) + len(_record(0x000A))
    boundsheet = _record(0x0085, struct.pack('<IBBB', sheet_offset, 0, 0, len(name)) + b'\0' + name)
    return globals_prefix + boundsheet + _record(0x000A) + sheet


def _directory_entry(name, kind, start, size, child=0xFFFFFFFF):
    encoded = (name + '\0').encode('utf-16le')
    assert len(encoded) <= 64
    result = bytearray(128)
    result[:len(encoded)] = encoded
    struct.pack_into('<HBBIII', result, 64, len(encoded), kind, 1, 0xFFFFFFFF, 0xFFFFFFFF, child)
    struct.pack_into('<IQ', result, 116, start, size)
    return bytes(result)


def _ole_container(workbook):
    # Avoid OLE mini-streams by placing the Workbook in >= 4096 standard bytes.
    sector = 512
    stream_size = max(len(workbook), 4096)
    blocks = (stream_size + sector - 1) // sector
    assert blocks + 2 < 128, 'Unexpectedly large synthetic workbook'
    workbook = workbook.ljust(blocks * sector, b'\0')
    header = bytearray(512)
    header[:8] = bytes.fromhex('D0CF11E0A1B11AE1')
    struct.pack_into('<HHHHHH', header, 24, 0x003E, 3, 0xFFFE, 9, 6, 0)
    struct.pack_into('<IIIIIIIII', header, 40, 0, 1, 0, 0, 4096,
                     0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into('<I', header, 76, blocks + 1)
    for j in range(1, 109):
        struct.pack_into('<I', header, 76 + j * 4, 0xFFFFFFFF)
    directory = (_directory_entry('Root Entry', 5, 0xFFFFFFFE, 0, 1)
                 + _directory_entry('Workbook', 2, 1, len(workbook))
                 + bytes(256))
    fat = [0xFFFFFFFE] + list(range(2, blocks + 1))
    fat += [0xFFFFFFFE, 0xFFFFFFFD]
    fat += [0xFFFFFFFF] * (128 - len(fat))
    return bytes(header) + directory + workbook + struct.pack('<128I', *fat)


def render_melli(case, destination: Path):
    rows = [list(MELLI_HEADERS)]
    for pos, entry in enumerate(case['rows'], 1):
        rows.append([pos, entry['date'], entry['time'],
             'واریز' if entry['direction'] == 'credit' else 'برداشت',
             int(entry['amount']), entry['reference'], 'تست ساختگی',
             entry['description'], entry['id'], int(entry['balance']),
             'نمونه', 'شعبه فرضی', entry['serial'], 'TEST ONLY'])
    matrix = [['گزارش ساختگی بانک ملی — هیچ داده واقعی وجود ندارد'],
              ['شماره حساب: TEST ONLY'], ['بازه فرضی ۱۴۰۵/۰۷'], [],
              rows[0], *rows[1:], ['پایان گزارش آزمایشی']]
    destination.write_bytes(_ole_container(_workbook(matrix)))
    return destination


def render_mellat(case, destination: Path, *, encoding='utf-8-sig'):
    with destination.open('w', encoding=encoding, newline='') as handle:
        writer = csv.writer(handle, lineterminator='\r\n')
        writer.writerow(['گزارش کاملاً ساختگی ملت'])
        writer.writerow(['TEST ONLY'])
        writer.writerow(MELLAT_HEADERS)
        for pos, entry in enumerate(case['rows'], 1):
            writer.writerow([pos, entry['date'], entry['time'], entry['serial'],
              entry['description'], entry['amount'] if entry['direction'] == 'debit' else '0',
              entry['amount'] if entry['direction'] == 'credit' else '0',
              entry['balance'], 'ذینفع فرضی', 'نمونه', entry['reference'], entry['id']])
    return destination


def render_small_utf8_bom(destination: Path):
    with destination.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(MELLAT_HEADERS)
        writer.writerow(['1', '1405/07/01', '08:00:00', '0000024', 'آزمون BOM', '125', '0', '9875', '', '', 'TEST', ''])
    return destination


def render_small_cp1256(destination: Path):
    with destination.open('w', encoding='cp1256', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow([text.replace('ی', 'ي') for text in MELLAT_HEADERS])
        writer.writerow(['1', '1405/07/01', '08:00:00', '0000025',
                         'كارمزد آزمايشي', '125', '0', '9875', '', '', 'TEST', ''])
    return destination
