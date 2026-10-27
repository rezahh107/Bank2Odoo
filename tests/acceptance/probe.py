"""Independent narrow OLE/BIFF8 readback for the public synthetic fixture.

Not a general spreadsheet parser and never used as a production converter.
"""
import struct


def inspect_biff8(path):
    data = path.read_bytes()
    if data[:8] != bytes.fromhex('D0CF11E0A1B11AE1'):
        raise ValueError('OLE signature mismatch')
    if struct.unpack_from('<H', data, 30)[0] != 9:
        raise ValueError('Expected 512-byte OLE sectors')
    fat_sid = struct.unpack_from('<I', data, 76)[0]
    fat = struct.unpack_from('<128I', data, 512 * (fat_sid + 1))
    dir_sid = struct.unpack_from('<I', data, 48)[0]
    directory = data[512 * (dir_sid + 1):512 * (dir_sid + 2)]
    entries = [directory[pos:pos + 128] for pos in range(0, 512, 128)]
    workbook = next((e for e in entries if e[66] == 2 and
        e[:struct.unpack_from('<H', e, 64)[0] - 2].decode('utf-16le') == 'Workbook'), None)
    if workbook is None:
        raise ValueError('OLE Workbook stream absent')
    sector_id = struct.unpack_from('<I', workbook, 116)[0]
    stream_size = struct.unpack_from('<Q', workbook, 120)[0]
    payload = bytearray()
    seen = set()
    while sector_id != 0xFFFFFFFE:
        if sector_id >= 128 or sector_id in seen:
            raise ValueError('Invalid FAT chain')
        seen.add(sector_id)
        payload.extend(data[512 * (sector_id + 1):512 * (sector_id + 2)])
        sector_id = fat[sector_id]
    stream = bytes(payload[:stream_size])
    if struct.unpack_from('<H', stream)[0] != 0x0809:
        raise ValueError('BIFF BOF absent')
    pos = 0
    sheet_offset = None
    while pos + 4 <= len(stream):
        code, length = struct.unpack_from('<HH', stream, pos)
        value = stream[pos + 4:pos + 4 + length]
        if code == 0x0085:
            sheet_offset = struct.unpack_from('<I', value)[0]
        pos += 4 + length
        if code == 0x000A:
            break
    if sheet_offset is None or struct.unpack_from('<H', stream, sheet_offset)[0] != 0x0809:
        raise ValueError('Missing worksheet offset')
    cells = {}
    pos = sheet_offset
    while pos + 4 <= len(stream):
        code, length = struct.unpack_from('<HH', stream, pos)
        value = stream[pos + 4:pos + 4 + length]
        if code == 0x0204:
            row, col, _, size, unicode_flag = struct.unpack_from('<HHHHB', value)
            if unicode_flag != 1:
                raise ValueError('Expected UTF-16 BIFF label')
            cells[row, col] = value[9:9 + size * 2].decode('utf-16le')
        elif code == 0x0203:
            row, col, _, number = struct.unpack('<HHHd', value)
            if number != int(number):
                raise ValueError('Unexpected floating-point fixture amount')
            cells[row, col] = int(number)
        pos += 4 + length
        if code == 0x000A:
            break
    return cells
